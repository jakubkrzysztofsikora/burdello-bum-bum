"""Celery task definitions for the transcript processing pipeline.

Provides a chain of tasks that transform raw transcript files into
searchable, mined knowledge:

    extract -> normalize -> chunk -> embed -> mine

Each task is idempotent and safe to retry.  Failed tasks are re-tried
up to 3 times with exponential backoff.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from celery import chain, shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.database import AsyncSessionLocal
from backend.core.models import Transcript
from backend.pipeline.chunking import SemanticChunker
from backend.pipeline.discovery import SourceDiscovery
from backend.pipeline.embedding import EmbeddingEngine
from backend.pipeline.normalization import TranscriptNormalizer
from backend.pipeline.storage import PipelineStorage
from backend.search.engine import HybridSearchEngine
from backend.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Built-in skills are discovered once per worker process and reused across
# tasks (extract_task delegates JSONL/Markdown parsing to them).
_skill_registry: SkillRegistry | None = None


def _get_skill_registry() -> SkillRegistry:
    """Return a process-wide, lazily-discovered skill registry."""
    global _skill_registry
    if _skill_registry is None:
        registry = SkillRegistry()
        registry.discover_builtin_skills()
        _skill_registry = registry
    return _skill_registry


def _message_content_to_str(content: Any) -> str:
    """Coerce a NormalizedMessage content (str/list/dict) into plain text."""
    if isinstance(content, str):
        return content
    return json.dumps(content, default=str, ensure_ascii=False)


# The sentence-transformers model is expensive to load (~1GB resident). Cache
# the chunker and embedder per worker process so the model loads once instead
# of on every task — the dominant cost when ingesting at scale.
_semantic_chunker: SemanticChunker | None = None
_embedding_engine: EmbeddingEngine | None = None


def _get_semantic_chunker() -> SemanticChunker:
    """Return a process-wide, lazily-loaded semantic chunker."""
    global _semantic_chunker
    if _semantic_chunker is None:
        _semantic_chunker = SemanticChunker(
            max_chunk_size=get_settings().BB_CHUNK_SIZE,
        )
    return _semantic_chunker


def _get_embedding_engine() -> EmbeddingEngine:
    """Return a process-wide, lazily-loaded embedding engine."""
    global _embedding_engine
    if _embedding_engine is None:
        _embedding_engine = EmbeddingEngine()
    return _embedding_engine


# Reuse one QdrantClient per worker process; constructing HybridSearchEngine
# per task does a health-check round-trip to Qdrant every time.
_search_engine: HybridSearchEngine | None = None


def _get_search_engine() -> HybridSearchEngine:
    """Return a process-wide, lazily-constructed hybrid search engine."""
    global _search_engine
    if _search_engine is None:
        settings = get_settings()
        _search_engine = HybridSearchEngine(
            qdrant_url=settings.QDRANT_URL,
            collection_name=settings.QDRANT_COLLECTION,
        )
    return _search_engine


async def _link_session_bookmarks(db: AsyncSession, transcript_id: uuid.UUID) -> None:
    """Best-effort: link any bookmarks for this transcript's session.

    Called at the ``completed`` transition (after chunks/embeddings are stored
    and the transcript is searchable) rather than at mine-tail, so bookmark
    linking does not depend on the failure-prone LLM mining stage (plan R3 /
    architect #1).

    Isolated in a SAVEPOINT so a linker failure rolls back ONLY the link UPDATE
    and never poisons the caller's outer transaction — the surrounding
    ``await db.commit()`` of chunks/status stays valid (architect #2). Fully
    non-fatal: any error is logged and swallowed.
    """
    from backend.pipeline.bookmark_linker import link_bookmarks_for_session

    try:
        session_id = (
            await db.execute(
                select(Transcript.session_id).where(Transcript.id == transcript_id)
            )
        ).scalar_one_or_none()
        if not session_id:
            return
        async with db.begin_nested():  # SAVEPOINT — isolates linker failure
            linked = await link_bookmarks_for_session(db, session_id)
        if linked:
            logger.info(
                "linked %d bookmark(s) to transcript %s (session %s)",
                linked,
                transcript_id,
                session_id,
            )
    except Exception:
        logger.exception(
            "bookmark linking failed for transcript %s (non-fatal)",
            transcript_id,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_source(self, source_path: str, provider_hint: str | None = None) -> dict[str, Any]:
    """Run the full processing pipeline on a single source file.

    This is the main entry-point task.  It chains the individual
    pipeline stages together via Celery's ``chain`` primitive.

    Args:
        source_path: Absolute path to the transcript file.
        provider_hint: Optional provider identifier override.

    Returns:
        Dict with ``task_id`` and ``status`` of the launched chain.
    """
    logger.info("process_source: launching pipeline for %s", source_path)

    # Launch the pipeline chain. chunk+embed are fused into one task so a large
    # fan-out doesn't run every chunk_task before any embed_task (FIFO staging):
    # each transcript reaches `completed` before the next starts, keeping the
    # mining queue fed instead of starved behind the whole chunk backlog.
    # knowledge_extract_task runs after mine_task so the LLM has access to
    # transcript text once the transcript is `completed`.
    result = (
        extract_task.s(source_path, provider_hint)
        | normalize_task.s()
        | chunk_embed_task.s()
        | mine_task.s()
        | knowledge_extract_task.s()
    ).apply_async()

    return {
        "task_id": result.id,
        "status": "started",
        "source_path": source_path,
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def extract_task(self, source_path: str, provider: str | None = None) -> dict[str, Any]:
    """Extract transcript data from a source file.

    Delegates to the best-matching provider skill (Claude Code, Codex, Kimi,
    Vibe, Agy, Aider, …) to parse the file into structured messages. Falls
    back to a raw text read when no skill matches or parsing yields nothing.

    Args:
        source_path: Path to the source file.
        provider: Provider identifier (e.g. ``claude_code``).

    Returns:
        Dict with ``source_path``, ``provider``, and ``extracted`` data.
    """
    path = Path(source_path)

    # Auto-detect provider from path if not given
    if not provider:
        provider = _detect_provider(source_path)

    # Try provider-specific skill extraction first.
    chosen = None
    try:
        transcripts = _get_skill_registry().extract(path)
        chosen = next(
            (t for t in transcripts if t.messages),
            transcripts[0] if transcripts else None,
        )
    except Exception:
        logger.exception("extract_task: skill extraction failed for %s", source_path)

    if chosen is not None and chosen.messages:
        messages = [
            {
                "speaker": m.speaker,
                "content": _message_content_to_str(m.content),
                "sequence": m.sequence,
            }
            for m in chosen.messages
        ]
        raw_text = chosen.raw_text or "\n".join(
            f"{m['speaker'] or 'unknown'}: {m['content']}" for m in messages
        )
        extracted = {
            "source_type": chosen.source_type or provider,
            "title": chosen.title or path.name,
            "raw_text": raw_text,
            "language": chosen.language or "en",
            "messages": messages,
            "metadata": {
                "file_path": source_path,
                "extraction_method": "skill",
                "skill": chosen.skill_name,
                "session_id": chosen.session_id,
                "project_name": chosen.project_name,
                **chosen.metadata,
            },
        }
    else:
        # Fallback: raw text read (no matching skill or nothing parsed).
        try:
            with open(source_path, "r", encoding="utf-8", errors="replace") as fh:
                raw_text = fh.read()
        except Exception as exc:
            logger.exception("extract_task: failed to read %s", source_path)
            raise self.retry(exc=exc) from exc

        extracted = {
            "source_type": provider,
            "title": path.name,
            "raw_text": raw_text,
            "language": "en",
            "messages": [],
            "metadata": {
                "file_path": source_path,
                "extraction_method": "text_read",
            },
        }

    # Deterministic project identity from path — overrides whatever the LLM
    # will try to invent in mine_task. See backend/pipeline/repo_resolver.py.
    from backend.pipeline.repo_resolver import resolve_from_path, resolve_from_cwd
    identity = resolve_from_path(source_path)

    # Non-Claude providers (Kimi, Gemini, Codex) always resolve to
    # "unsorted-*" from path alone — their session files live under
    # flat provider dirs with no project segment. When session
    # metadata carries a cwd (common for Codex), resolve the REAL
    # project via resolve_from_cwd and override the bucket identity.
    if identity is not None and identity.slug.startswith("unsorted-"):
        cwd = extracted.get("metadata", {}).get("cwd")
        if cwd:
            cwd_identity = resolve_from_cwd(cwd)
            if cwd_identity is not None:
                identity = cwd_identity

    return {
        "source_path": source_path,
        "provider": provider,
        "extracted": extracted,
        "repo_slug": identity.slug if identity else None,
        "repo_humanized": identity.humanized if identity else None,
        "repo_owner": identity.owner if identity else None,
        "repo_provider": identity.provider if identity else None,
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def normalize_task(self, extraction_result: dict[str, Any]) -> dict[str, Any]:
    """Normalise extracted data and store in the database.

    Args:
        extraction_result: Output from ``extract_task``.

    Returns:
        Dict with ``transcript_id`` and related metadata.
    """
    import asyncio

    extracted_data = extraction_result["extracted"]
    provider = extraction_result["provider"]
    source_path = extraction_result["source_path"]

    async def _normalize() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            # Build search engine (cached per process)
            storage = PipelineStorage(db=db, search_engine=_get_search_engine())

            # Compute file hash for dedup
            from backend.pipeline.discovery import SourceDiscovery
            discovery = SourceDiscovery()
            file_hash = discovery.compute_hash(Path(source_path))

            # Skip if already processed (idempotency)
            if await storage.source_exists(file_hash):
                logger.info("normalize_task: source already exists (hash=%s)", file_hash)
                # Find existing source + transcript via explicit queries — async
                # SQLAlchemy can't lazy-load `Source.transcripts` outside the
                # greenlet context, so resolve the transcript_id directly.
                from sqlalchemy import select
                from backend.core.models import Source, Transcript
                source_row = (
                    await db.execute(
                        select(Source.id).where(
                            Source.metadata_["file_hash"].as_string() == file_hash
                        )
                    )
                ).scalar_one()
                transcript_row = (
                    await db.execute(
                        select(Transcript)
                        .where(Transcript.source_id == source_row)
                        .order_by(Transcript.created_at.asc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if transcript_row is not None and transcript_row.status == "processing":
                    # A worker kill can leave a transcript in ``processing``
                    # with messages stored but no chunks (chunk_embed was cut
                    # before marking completed). Re-dispatch chunk_embed to
                    # resume it; the plain already_exists return below would
                    # otherwise leave it stuck forever. Returns a null
                    # transcript_id so this chain's own chunk_embed no-ops and
                    # the re-dispatched task does the real work — no double
                    # chunking.
                    from backend.pipeline.tasks import chunk_embed_task

                    chunk_embed_task.delay(
                        {"transcript_id": str(transcript_row.id), "resume": True}
                    )
                    logger.info(
                        "normalize_task: resumed stuck processing transcript %s",
                        transcript_row.id,
                    )
                    return {
                        "transcript_id": None,
                        "source_id": str(source_row),
                        "status": "skipped",
                        "reason": "already_exists_resumed",
                    }
                return {
                    "transcript_id": str(transcript_row.id) if transcript_row else None,
                    "source_id": str(source_row),
                    "status": "skipped",
                    "reason": "already_exists",
                }

            # Store source. Prefer the skill's source_type over the path-detected provider.
            source_type = extracted_data.get("source_type") or provider
            size = Path(source_path).stat().st_size
            source_id = await storage.store_source(source_path, file_hash, source_type, size)

            # Build ExtractedTranscript and normalise
            from backend.skills.base import ExtractedTranscript, NormalizedMessage

            messages = [
                NormalizedMessage(
                    speaker=msg.get("speaker"),
                    content=msg.get("content", ""),
                    sequence=idx,
                )
                for idx, msg in enumerate(extracted_data.get("messages", []))
            ]

            extracted = ExtractedTranscript(
                source_type=extracted_data["source_type"],
                title=extracted_data.get("title"),
                raw_text=extracted_data.get("raw_text", ""),
                language=extracted_data.get("language", "en"),
                messages=messages,
                metadata=extracted_data.get("metadata", {}),
            )

            normalizer = TranscriptNormalizer()
            normalized = normalizer.normalize(extracted, source_id)

            # Store transcript + messages
            transcript_id = await storage.store_transcript(source_id, normalized)

            # Storage only flushes; commit so the rows survive the session.
            await db.commit()

            return {
                "transcript_id": str(transcript_id),
                "source_id": str(source_id),
                "status": "normalized",
                "message_count": len(messages),
            }

    try:
        result = asyncio.run(_normalize())
        return result
    except Exception as exc:
        logger.exception("normalize_task: failed")
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def chunk_task(self, normalize_result: dict[str, Any]) -> dict[str, Any]:
    """Chunk a transcript into semantically-grouped pieces.

    Args:
        normalize_result: Output from ``normalize_task``.

    Returns:
        Dict with ``transcript_id`` and ``chunk_count``.
    """
    import asyncio

    transcript_id_str = normalize_result.get("transcript_id")
    if not transcript_id_str:
        return {**normalize_result, "status": "error", "reason": "no_transcript_id"}

    transcript_id = uuid.UUID(transcript_id_str)

    async def _chunk() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            storage = PipelineStorage(db=db)

            # Fetch transcript text
            text = await storage.get_transcript_text(transcript_id)
            if not text:
                return {
                    "transcript_id": transcript_id_str,
                    "status": "error",
                    "reason": "empty_transcript",
                }

            # Chunk (model cached per process)
            chunker = _get_semantic_chunker()
            chunks = chunker.create_chunks(
                text,
                metadata={"transcript_id": transcript_id_str},
            )

            return {
                "transcript_id": transcript_id_str,
                "chunks": chunks,
                "chunk_count": len(chunks),
                "status": "chunked",
            }

    try:
        result = asyncio.run(_chunk())
        return result
    except Exception as exc:
        logger.exception("chunk_task: failed for %s", transcript_id_str)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def embed_task(self, chunk_result: dict[str, Any]) -> dict[str, Any]:
    """Generate embeddings for chunks and store in Qdrant.

    Args:
        chunk_result: Output from ``chunk_task``.

    Returns:
        Dict with ``transcript_id`` and ``embedded_count``.
    """
    import asyncio

    transcript_id_str = chunk_result.get("transcript_id")
    chunks = chunk_result.get("chunks", [])

    if not transcript_id_str or not chunks:
        return {**chunk_result, "status": "error", "reason": "no_chunks"}

    transcript_id = uuid.UUID(transcript_id_str)

    async def _embed() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            storage = PipelineStorage(db=db, search_engine=_get_search_engine())

            # Generate embeddings (model cached per process)
            engine = _get_embedding_engine()
            embedded_chunks = engine.embed_chunks(chunks)

            # Store in DB + Qdrant
            chunk_ids = await storage.store_chunks(transcript_id, embedded_chunks)

            # Update transcript status
            await storage.update_transcript_status(transcript_id, "completed")

            # Transcript is now stored + searchable — link any pending bookmarks.
            await _link_session_bookmarks(db, transcript_id)

            # Storage only flushes; commit so chunks + status survive.
            await db.commit()

            return {
                "transcript_id": transcript_id_str,
                "embedded_count": len(chunk_ids),
                "chunk_ids": [str(cid) for cid in chunk_ids],
                "status": "embedded",
            }

    try:
        result = asyncio.run(_embed())
        return result
    except Exception as exc:
        logger.exception("embed_task: failed for %s", transcript_id_str)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def chunk_embed_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Chunk AND embed a transcript in a single task.

    Combining the two stages avoids the FIFO staging problem when many
    transcripts are dispatched at once (the worker would otherwise run every
    chunk before any embed). Each transcript is fully processed to
    ``completed`` before the next, so progress is steady. Chains to mine_task.

    Args:
        payload: Dict with ``transcript_id``.

    Returns:
        Dict consumable by ``mine_task`` (``transcript_id``, ``status``).
    """
    import asyncio

    transcript_id_str = payload.get("transcript_id")
    if not transcript_id_str:
        return {**payload, "status": "error", "reason": "no_transcript_id"}

    transcript_id = uuid.UUID(transcript_id_str)

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            storage = PipelineStorage(db=db, search_engine=_get_search_engine())

            resume = bool(payload.get("resume")) and await storage.count_chunks(transcript_id) > 0
            if resume:
                # Continuation pass: shells already exist, only embed the
                # remaining NULL-embedding rows. Never re-chunk or delete.
                exhausted, done = await storage.embed_chunks_budgeted(
                    transcript_id,
                    embed_batch=_get_embedding_engine().embed_batch,
                    batch_size=64,
                    time_budget_ns=get_settings().BB_EMBED_TIME_BUDGET_SECONDS * 1_000_000_000,
                )
                if exhausted:
                    await db.commit()
                    chunk_embed_task.delay(
                        {"transcript_id": transcript_id_str, "resume": True}
                    )
                    # Don't let the chained mine_task run on a partially
                    # embedded transcript; the continuation owns completion.
                    return {
                        "transcript_id": None,
                        "status": "partial",
                        "embedded_count": done,
                    }
                await storage.index_transcript_chunks(transcript_id)
                await storage.update_transcript_status(transcript_id, "completed")
                await _link_session_bookmarks(db, transcript_id)
                await db.commit()
                return {
                    "transcript_id": transcript_id_str,
                    "status": "embedded",
                    "embedded_count": done,
                }

            text = await storage.get_transcript_text(transcript_id)
            if not text:
                return {
                    "transcript_id": transcript_id_str,
                    "status": "error",
                    "reason": "empty_transcript",
                }

            # Idempotent re-chunk: clear prior chunks so a fresh run never
            # duplicates (a wedged transcript may already have some).
            await storage.delete_chunks(transcript_id)

            chunks = _get_semantic_chunker().create_chunks(
                text, metadata={"transcript_id": transcript_id_str}
            )
            if not chunks:
                await storage.update_transcript_status(transcript_id, "completed")
                await _link_session_bookmarks(db, transcript_id)
                await db.commit()
                return {"transcript_id": transcript_id_str, "status": "no_chunks"}

            await storage.store_chunk_shells(
                transcript_id,
                chunks,
                enrichment=await storage.get_chunk_enrichment(transcript_id),
            )
            exhausted, done = await storage.embed_chunks_budgeted(
                transcript_id,
                embed_batch=_get_embedding_engine().embed_batch,
                batch_size=64,
                time_budget_ns=get_settings().BB_EMBED_TIME_BUDGET_SECONDS * 1_000_000_000,
            )
            await db.commit()
            if exhausted:
                # Budget consumed before the queue drained — hand off to a
                # resume pass instead of risking a 1h kill.
                chunk_embed_task.delay(
                    {"transcript_id": transcript_id_str, "resume": True}
                )
                return {
                    "transcript_id": None,
                    "status": "partial",
                    "embedded_count": done,
                }

            await storage.index_transcript_chunks(transcript_id)
            await storage.update_transcript_status(transcript_id, "completed")
            await _link_session_bookmarks(db, transcript_id)
            await db.commit()

            return {
                "transcript_id": transcript_id_str,
                "embedded_count": done,
                "status": "embedded",
            }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception("chunk_embed_task: failed for %s", transcript_id_str)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=100, default_retry_delay=90)
def mine_task(self, embed_result: dict[str, Any]) -> dict[str, Any]:
    """Run LLM data mining on a transcript.

    Args:
        embed_result: Output from ``embed_task``.

    Returns:
        Dict with mining results.
    """
    import asyncio

    transcript_id_str = embed_result.get("transcript_id")
    if not transcript_id_str:
        return {**embed_result, "status": "error", "reason": "no_transcript_id"}

    transcript_id = uuid.UUID(transcript_id_str)

    async def _mine() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            storage = PipelineStorage(db=db)
            text = await storage.get_transcript_text(transcript_id)

            if not text:
                return {
                    "transcript_id": transcript_id_str,
                    "status": "error",
                    "reason": "empty_transcript",
                }

            settings = get_settings()
            from backend.mining.engine import MiningEngine
            from backend.pipeline.repo_resolver import resolve_from_path
            from sqlalchemy import select
            from backend.core.models import Source, Transcript

            engine = MiningEngine(
                litellm_url=settings.LITELLM_URL,
            )

            # Resolve the canonical project identity from the source path
            # BEFORE mining so we can short-circuit the LLM extract_projects
            # call (its output would be discarded anyway).
            source_path_row = (
                await db.execute(
                    select(Source.metadata_["file_path"].as_string())
                    .join(Transcript, Transcript.source_id == Source.id)
                    .where(Transcript.id == transcript_id)
                )
            ).scalar_one_or_none()

            from backend.pipeline.repo_resolver import resolve_from_path, resolve_from_cwd
            identity = (
                resolve_from_path(source_path_row) if source_path_row else None
            )

            # Non-Claude providers (Kimi, Gemini, Codex) always resolve to
            # "unsorted-*" from path alone. When the transcript metadata
            # carries a cwd, resolve the REAL project via resolve_from_cwd.
            if identity is not None and identity.slug.startswith("unsorted-"):
                transcript_meta = (
                    await db.execute(
                        select(Transcript.metadata_).where(Transcript.id == transcript_id)
                    )
                ).scalar_one_or_none()
                cwd = (transcript_meta or {}).get("cwd")
                if cwd:
                    cwd_identity = resolve_from_cwd(cwd)
                    if cwd_identity is not None:
                        identity = cwd_identity

            results = await engine.mine_transcript(
                transcript_id,
                text,
                project_context=identity.humanized if identity else None,
            )

            # Replace whatever projects field we have with the deterministic
            # identity. The LLM keeps producing tasks/artifacts/status; only
            # its project guesses are discarded.
            if identity is not None:
                results["projects"] = [{
                    "name": identity.humanized,
                    "description": (
                        f"{identity.provider} transcripts for {identity.humanized}"
                    ),
                    "status": "active",
                    "confidence": 1.0,
                }]
            else:
                # Path didn't match a known provider; drop the LLM's guesses
                # rather than persisting noise. Tasks/artifacts will attach
                # with project_id=NULL.
                results["projects"] = []

            # Persist the mining output (projects/tasks/artifacts/raw rows).
            counts = await storage.store_mining_results(transcript_id, results)

            # Idempotent safety-net re-link (primary linking happens at the
            # `completed` transition in embed/chunk_embed). Savepoint-isolated
            # and fully non-fatal — see _link_session_bookmarks.
            await _link_session_bookmarks(db, transcript_id)

            await db.commit()

            return {
                "transcript_id": transcript_id_str,
                "stored": counts,
                "status": "mined",
                "repo_slug": identity.slug if identity else None,
                "repo_humanized": identity.humanized if identity else None,
            }

    try:
        result = asyncio.run(_mine())
        return result
    except Exception as exc:
        logger.exception("mine_task: failed for %s", transcript_id_str)
        raise self.retry(exc=exc) from exc


# Common patterns of secrets that may appear inside transcript excerpts.
# Match the value but keep the prefix/suffix so humans can see what was
# redacted (e.g. "sk-XXXX" → "sk-[REDACTED]"). Transcripts are user content
# and may legitimately include credentials; we never want them persisting
# into KB atoms that become public.
_SECRET_PATTERNS: tuple[str, ...] = (
    r"\bsk-[A-Za-z0-9_-]{20,}",
    r"\bsk_live_[A-Za-z0-9]{16,}",
    r"\bghp_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abp]-[A-Za-z0-9-]{10,}",
    r"\bAIza[0-9A-Za-z_-]{30,}",
    r"\bAKIA[0-9A-Z]{16}",
    r"\bASIA[0-9A-Z]{16}",
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
)


def _scrub_secrets(text: str | None) -> str | None:
    """Redact likely secrets from a free-text excerpt.

    Args:
        text: Excerpt that may contain credentials.

    Returns:
        The text with matched secret values replaced by ``[REDACTED]``,
        or ``None`` when the input is ``None``.
    """
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = re.sub(pat, "[REDACTED]", out)
    return out


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def knowledge_extract_task(
    self, mine_result: dict[str, Any]
) -> dict[str, Any]:
    """Extract reusable engineering knowledge atoms from a transcript.

    Runs after ``mine_task``. Calls the LLM with an injection-safe prompt,
    scrubs any secrets from the resulting excerpts, and persists the atoms
    as a ``MiningResult(miner_type='knowledge')`` row so downstream
    clustering can group them into KB nodes.

    Args:
        mine_result: Output from ``mine_task``. Only ``transcript_id`` is
            required; the rest is passed through unchanged.

    Returns:
        Dict with ``transcript_id`` and ``atom_count`` on success; on
        transient LLM failure the task is retried up to ``max_retries``.
    """
    import asyncio
    import re

    transcript_id_str = mine_result.get("transcript_id")
    if not transcript_id_str:
        return {**mine_result, "status": "error", "reason": "no_transcript_id"}

    transcript_id = uuid.UUID(transcript_id_str)

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            storage = PipelineStorage(db=db)
            text = await storage.get_transcript_text(transcript_id)
            if not text:
                return {
                    "transcript_id": transcript_id_str,
                    "atom_count": 0,
                    "status": "skipped",
                    "reason": "empty_transcript",
                }

            settings = get_settings()
            from backend.mining.engine import MiningEngine

            engine = MiningEngine(litellm_url=settings.LITELLM_URL)
            atoms = await engine.extract_knowledge(text)

            # Defensive: scrub secrets from excerpts before persisting. The
            # prompt already instructs the model to redact; this is a
            # belt-and-braces second pass.
            for atom in atoms:
                atom["excerpt"] = _scrub_secrets(atom.get("excerpt"))
                atom["summary"] = _scrub_secrets(atom.get("summary"))

            from backend.core.models import MiningResult

            # Idempotency: only this miner's rows are wiped before re-insert,
            # so a re-run of mine_task never nukes knowledge atoms.
            await storage.delete_mining_results_by_type(
                transcript_id, "knowledge"
            )

            if atoms:
                avg_conf = sum(
                    float(a.get("confidence") or 0.0) for a in atoms
                ) / len(atoms)
                db.add(
                    MiningResult(
                        transcript_id=transcript_id,
                        miner_type="knowledge",
                        result_data={"atoms": atoms},
                        confidence=avg_conf,
                        metadata_={"atom_count": len(atoms)},
                    )
                )

            await db.commit()

            return {
                "transcript_id": transcript_id_str,
                "atom_count": len(atoms),
                "status": "ok",
            }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception(
            "knowledge_extract_task: failed for %s", transcript_id_str
        )
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_provider(path: str) -> str:
    """Detect the transcript provider from the file path.

    Args:
        path: Absolute or relative file path.

    Returns:
        Provider identifier string.
    """
    path_lower = path.lower()
    if ".claude" in path_lower:
        return "claude_code"
    if ".codex" in path_lower:
        return "codex"
    if ".kimi" in path_lower:
        return "kimi"
    if ".vibe" in path_lower:
        return "vibe"
    if ".gemini" in path_lower or "antigravity" in path_lower:
        return "agy"
    if ".aider" in path_lower:
        return "aider"
    return "unknown"
