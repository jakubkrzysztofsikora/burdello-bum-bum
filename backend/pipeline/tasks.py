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
import uuid
from pathlib import Path
from typing import Any

from celery import chain, shared_task

from backend.core.config import get_settings
from backend.core.database import AsyncSessionLocal
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

    # Launch the pipeline chain
    result = (
        extract_task.s(source_path, provider_hint)
        | normalize_task.s()
        | chunk_task.s()
        | embed_task.s()
        | mine_task.s()
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

    return {
        "source_path": source_path,
        "provider": provider,
        "extracted": extracted,
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
            # Build search engine
            settings = get_settings()
            search_engine = HybridSearchEngine(
                qdrant_url=settings.QDRANT_URL,
                collection_name=settings.QDRANT_COLLECTION,
            )
            storage = PipelineStorage(db=db, search_engine=search_engine)

            # Compute file hash for dedup
            from backend.pipeline.discovery import SourceDiscovery
            discovery = SourceDiscovery()
            file_hash = discovery.compute_hash(Path(source_path))

            # Skip if already processed (idempotency)
            if await storage.source_exists(file_hash):
                logger.info("normalize_task: source already exists (hash=%s)", file_hash)
                # Find existing source and transcript
                from sqlalchemy import select
                from backend.core.models import Source
                result = await db.execute(
                    select(Source).where(
                        Source.metadata_["file_hash"].as_string() == file_hash
                    )
                )
                existing = result.scalar_one()
                return {
                    "transcript_id": str(existing.transcripts[0].id) if existing.transcripts else None,
                    "source_id": str(existing.id),
                    "status": "skipped",
                    "reason": "already_exists",
                }

            # Store source
            size = Path(source_path).stat().st_size
            source_id = await storage.store_source(source_path, file_hash, provider, size)

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
            settings = get_settings()
            storage = PipelineStorage(db=db)

            # Fetch transcript text
            text = await storage.get_transcript_text(transcript_id)
            if not text:
                return {
                    "transcript_id": transcript_id_str,
                    "status": "error",
                    "reason": "empty_transcript",
                }

            # Chunk
            chunker = SemanticChunker(
                max_chunk_size=settings.BB_CHUNK_SIZE,
            )
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
            settings = get_settings()
            search_engine = HybridSearchEngine(
                qdrant_url=settings.QDRANT_URL,
                collection_name=settings.QDRANT_COLLECTION,
            )
            storage = PipelineStorage(db=db, search_engine=search_engine)

            # Generate embeddings
            engine = EmbeddingEngine()
            embedded_chunks = engine.embed_chunks(chunks)

            # Store in DB + Qdrant
            chunk_ids = await storage.store_chunks(transcript_id, embedded_chunks)

            # Update transcript status
            await storage.update_transcript_status(transcript_id, "completed")

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


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
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

            engine = MiningEngine(
                litellm_url=settings.LITELLM_URL,
            )
            results = await engine.mine_transcript(transcript_id, text)

            # Persist the mining output (projects/tasks/artifacts/raw rows).
            counts = await storage.store_mining_results(transcript_id, results)
            await db.commit()

            return {
                "transcript_id": transcript_id_str,
                "stored": counts,
                "status": "mined",
            }

    try:
        result = asyncio.run(_mine())
        return result
    except Exception as exc:
        logger.exception("mine_task: failed for %s", transcript_id_str)
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
