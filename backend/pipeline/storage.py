"""Database and vector-store storage for processed transcripts.

Provides ``PipelineStorage`` which persists sources, transcripts, messages,
and chunks to PostgreSQL, and upserts chunk embeddings into Qdrant.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import (
    Artifact,
    Chunk,
    Message,
    MiningResult,
    Project,
    Source,
    Task,
    Transcript,
)
from backend.core.schemas import ARTIFACT_TYPES, MessageCreate, TranscriptCreate
from backend.search.engine import HybridSearchEngine

logger = logging.getLogger(__name__)


class PipelineStorage:
    """Stores processed pipeline data to PostgreSQL and Qdrant."""

    def __init__(
        self,
        db: AsyncSession,
        search_engine: HybridSearchEngine | None = None,
    ) -> None:
        """Initialise the storage layer.

        Args:
            db: An async SQLAlchemy session.
            search_engine: Optional ``HybridSearchEngine`` for Qdrant
                vector-store operations.
        """
        self.db = db
        self.search = search_engine

    async def store_source(
        self,
        path: str,
        file_hash: str,
        provider: str,
        size: int,
    ) -> uuid.UUID:
        """Insert a new source record into the database.

        Args:
            path: Absolute filesystem path to the source file.
            file_hash: SHA-256 hash of the file content.
            provider: Provider identifier (e.g. ``claude_code``).
            size: File size in bytes.

        Returns:
            The UUID of the newly created source.
        """
        source = Source(
            source_type=provider,
            external_id=file_hash,
            title=path.split("/")[-1] if "/" in path else path,
            url=f"file://{path}",
            metadata_={
                "file_path": path,
                "file_hash": file_hash,
                "file_size": size,
                "provider": provider,
            },
        )
        self.db.add(source)
        await self.db.flush()
        await self.db.refresh(source)

        logger.info("store_source: created source %s for %s", source.id, path)
        return source.id  # type: ignore[return-value]

    async def store_transcript(
        self,
        source_id: uuid.UUID,
        data: dict[str, Any],
    ) -> uuid.UUID:
        """Insert a transcript and its messages.

        Args:
            source_id: UUID of the parent source.
            data: Dict with ``transcript`` (TranscriptCreate) and
                ``messages`` (list of MessageCreate).

        Returns:
            The UUID of the newly created transcript.
        """
        transcript_create: TranscriptCreate = data["transcript"]
        message_creates: list[MessageCreate] = data.get("messages", [])

        transcript = Transcript(
            source_id=source_id,
            session_id=transcript_create.session_id
            or (transcript_create.metadata or {}).get("session_id"),
            title=transcript_create.title,
            raw_text=transcript_create.raw_text,
            language=transcript_create.language,
            status="processing",
            metadata_=transcript_create.metadata,
        )
        self.db.add(transcript)
        await self.db.flush()
        await self.db.refresh(transcript)

        transcript_id = transcript.id  # type: ignore[assignment]

        # Insert messages
        for msg_create in message_creates:
            message = Message(
                transcript_id=transcript_id,
                speaker=msg_create.speaker,
                content=msg_create.content,
                timestamp_seconds=msg_create.timestamp_seconds,
                sequence=msg_create.sequence,
                metadata_=msg_create.metadata,
            )
            self.db.add(message)

        await self.db.flush()
        logger.info(
            "store_transcript: created transcript %s with %d messages",
            transcript_id,
            len(message_creates),
        )
        return transcript_id  # type: ignore[return-value]

    async def store_chunks(
        self,
        transcript_id: uuid.UUID,
        chunks: list[dict[str, Any]],
    ) -> list[uuid.UUID]:
        """Insert chunks into PostgreSQL and upsert into Qdrant.

        Args:
            transcript_id: UUID of the parent transcript.
            chunks: List of chunk dicts with ``text``, ``embedding``,
                and optional ``metadata`` keys.

        Returns:
            List of chunk UUIDs created in PostgreSQL.
        """
        chunk_ids: list[uuid.UUID] = []
        db_chunks: list[Chunk] = []

        for idx, chunk_data in enumerate(chunks):
            chunk_id = uuid.uuid4()
            embedding = chunk_data.get("embedding")
            # Convert list to proper format for pgvector if needed
            if isinstance(embedding, list):
                embedding = [float(v) for v in embedding]

            chunk = Chunk(
                id=chunk_id,
                transcript_id=transcript_id,
                text=chunk_data["text"],
                embedding=embedding,
                chunk_index=idx,
                metadata_=chunk_data.get("metadata", {}),
            )
            self.db.add(chunk)
            db_chunks.append(chunk)
            chunk_ids.append(chunk_id)

        await self.db.flush()

        # Upsert into Qdrant
        if self.search is not None:
            try:
                await self.search.index_chunks(
                    [
                        {
                            "id": str(cid),
                            "transcript_id": str(transcript_id),
                            "text": chunk["text"],
                            "embedding": chunk.get("embedding"),
                            "metadata": chunk.get("metadata", {}),
                        }
                        for cid, chunk in zip(chunk_ids, chunks)
                    ]
                )
                logger.info(
                    "store_chunks: upserted %d chunks into Qdrant",
                    len(chunks),
                )
            except Exception:
                logger.exception("store_chunks: Qdrant upsert failed")
                # Don't raise — PostgreSQL is the source of truth

        return chunk_ids

    async def store_chunk_shells(
        self,
        transcript_id: uuid.UUID,
        chunks: list[dict[str, Any]],
        enrichment: dict[str, Any] | None = None,
    ) -> list[uuid.UUID]:
        """Insert unembedded chunk shells (embedding NULL) into PostgreSQL.

        Shells carry text + metadata; the embedding is filled in later, in
        bounded batches, so a huge transcript dodges the 1-hour task limit.

        Args:
            transcript_id: UUID of the parent transcript.
            chunks: List of chunk dicts with ``text`` and optional ``metadata``.
            enrichment: Optional project/source fields stamped onto every
                shell's metadata so the vector store can filter by them.

        Returns:
            List of chunk UUIDs created in PostgreSQL.
        """
        chunk_ids: list[uuid.UUID] = []
        for idx, chunk_data in enumerate(chunks):
            chunk_id = uuid.uuid4()
            metadata = dict(chunk_data.get("metadata", {}))
            if enrichment:
                metadata.update(enrichment)
            chunk = Chunk(
                id=chunk_id,
                transcript_id=transcript_id,
                text=chunk_data["text"],
                embedding=None,
                chunk_index=idx,
                metadata_=metadata,
            )
            self.db.add(chunk)
            chunk_ids.append(chunk_id)
        await self.db.flush()
        return chunk_ids

    async def load_unembedded_chunks(
        self,
        transcript_id: uuid.UUID,
        limit: int,
    ) -> list[tuple[uuid.UUID, str]]:
        """Return ``(chunk_id, text)`` for chunks still awaiting an embedding.

        Ordered by ``chunk_index`` (oldest first) and bounded by ``limit``
        so the embedder works in resumable slices.

        Args:
            transcript_id: UUID of the parent transcript.
            limit: Maximum number of chunks to return.

        Returns:
            List of ``(chunk_id, text)`` tuples.
        """
        rows = (
            await self.db.execute(
                select(Chunk.id, Chunk.text)
                .where(Chunk.transcript_id == transcript_id)
                .where(Chunk.embedding.is_(None))
                .order_by(Chunk.chunk_index)
                .limit(limit)
            )
        ).all()
        return [(r[0], r[1]) for r in rows]

    async def count_unembedded(self, transcript_id: uuid.UUID) -> int:
        """Count chunks that still have a NULL embedding for a transcript."""
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Chunk)
                    .where(Chunk.transcript_id == transcript_id)
                    .where(Chunk.embedding.is_(None))
                )
            ).scalar_one()
        )

    async def count_chunks(self, transcript_id: uuid.UUID) -> int:
        """Count all chunk rows (embedded or not) for a transcript."""
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Chunk)
                    .where(Chunk.transcript_id == transcript_id)
                )
            ).scalar_one()
        )

    async def update_chunk_embeddings(
        self,
        transcript_id: uuid.UUID,
        embeddings: dict[uuid.UUID, list[float]],
    ) -> None:
        """Stamp computed embeddings onto chunk rows.

        Args:
            transcript_id: UUID of the parent transcript (safety guard).
            embeddings: Mapping of chunk UUID to 768-dim vector.
        """
        if not embeddings:
            return
        for chunk_id, vector in embeddings.items():
            await self.db.execute(
                update(Chunk)
                .where(Chunk.transcript_id == transcript_id)
                .where(Chunk.id == chunk_id)
                .values(embedding=[float(v) for v in vector])
                .execution_options(synchronize_session="fetch")
            )

    async def embed_chunks_budgeted(
        self,
        transcript_id: uuid.UUID,
        embed_batch: Any,
        batch_size: int,
        time_budget_ns: int,
    ) -> tuple[bool, int]:
        """Embed a transcript's outstanding chunks in bounded, time-guarded batches.

        Fetches unembedded chunks in slices of ``batch_size``, embeds each via
        ``embed_batch``, and writes vectors back. If the wall-clock budget is
        consumed before the queue drains, returns ``(exhausted=True, done)`` so
        the caller can re-dispatch a continuation; the remaining NULL-embedding
        rows are exactly the resume point.

        Args:
            transcript_id: UUID of the parent transcript.
            embed_batch: Callable ``(texts: list[str]) -> list[list[float]]``.
            batch_size: Max chunks per embed call.
            time_budget_ns: Nanoseconds of wall time before handing back.

        Returns:
            ``(budget_exhausted, chunks_completed)``.
        """
        import time as _time

        done = 0
        start = _time.monotonic()
        while True:
            batch = await self.load_unembedded_chunks(transcript_id, limit=batch_size)
            if not batch:
                return False, done
            texts = [text for _, text in batch]
            vectors = embed_batch(texts)
            await self.update_chunk_embeddings(
                transcript_id,
                {cid: vector for cid, vector in zip((cid for cid, _ in batch), vectors)},
            )
            await self.db.flush()
            done += len(batch)
            if _time.monotonic() - start >= time_budget_ns / 1e9:
                return True, done
        return False, done

    async def index_transcript_chunks(self, transcript_id: uuid.UUID) -> int:
        """Upsert a transcript's fully-embedded chunks into Qdrant.

        Reads chunks from PostgreSQL (the source of truth) after the resumable
        embed pass finishes and indexes any that are not yet in Qdrant. Only
        chunks with a non-null embedding are indexed.

        Chunks created before project enrichment existed are backfilled here:
        missing ``project_id``/``source_type`` fields are stamped from the
        source context (creating the Project row on demand) so re-indexed data
        matches the filter contract, and the result is persisted back to
        PostgreSQL to keep it authoritative.

        Args:
            transcript_id: UUID of the parent transcript.

        Returns:
            Number of chunks indexed.
        """
        if self.search is None:
            return 0
        rows = (
            await self.db.execute(
                select(Chunk)
                .where(Chunk.transcript_id == transcript_id)
                .where(Chunk.embedding.isnot(None))
                .order_by(Chunk.chunk_index)
            )
        ).scalars().all()
        if not rows:
            return 0

        enrichment = await self.get_chunk_enrichment(transcript_id)
        changed: list[Chunk] = []
        chunks: list[dict[str, Any]] = []
        for c in rows:
            metadata = dict(c.metadata_ or {})
            if "project_id" not in metadata:
                metadata.update(enrichment)
                c.metadata_ = metadata
                changed.append(c)
            chunks.append(
                {
                    "id": str(c.id),
                    "transcript_id": str(transcript_id),
                    "text": c.text,
                    "embedding": c.embedding,
                    "metadata": metadata,
                }
            )
        if changed:
            await self.db.flush()
        try:
            await self.search.index_chunks(chunks)
        except Exception:
            logger.exception("index_transcript_chunks: Qdrant upsert failed")
        return len(chunks)

    async def get_or_create_project_by_name(
        self, name: str, description: str | None = None
    ) -> uuid.UUID:
        """Return the Project id for ``name``, creating it if absent.

        Race-safe: parallel callers that both miss the SELECT resolve on the
        UNIQUE(name) constraint via a savepoint-scoped insert.

        Args:
            name: Canonical humanized project name.
            description: Optional description on first creation.

        Returns:
            The Project's UUID.
        """
        existing = (
            await self.db.execute(select(Project).where(Project.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id  # type: ignore[return-value]
        project = Project(
            name=name,
            description=description,
            status="active",
            metadata_={"confidence": 1.0},
        )
        try:
            async with self.db.begin_nested():
                self.db.add(project)
                await self.db.flush()
        except IntegrityError:
            existing = (
                await self.db.execute(select(Project).where(Project.name == name))
            ).scalar_one()
            return existing.id  # type: ignore[return-value]
        return project.id  # type: ignore[return-value]

    async def get_chunk_enrichment(
        self, transcript_id: uuid.UUID, humanized: str | None = None
    ) -> dict[str, Any]:
        """Resolve project + source context to stamp onto chunk metadata.

        Returns a dict with ``project_id``, ``source_type``, and ``created_at``
        so a transcript's chunks are filterable by those fields in Qdrant. When
        no source row or identity can be resolved, returns only what exists
        (never raising).

        Args:
            transcript_id: UUID of the parent transcript.
            humanized: Optional pre-resolved project humanized name; if omitted
                the source path is resolved via ``resolve_from_path``.

        Returns:
            Field dict (possibly empty) to merge into chunk metadata.
        """
        row = (
            await self.db.execute(
                select(
                    Source.metadata_["file_path"].as_string(),
                    Source.source_type,
                    Source.created_at,
                )
                .join(Transcript, Transcript.source_id == Source.id)
                .where(Transcript.id == transcript_id)
            )
        ).first()
        if row is None:
            return {}
        file_path, source_type, created_at = row[0], row[1], row[2]

        enrichment: dict[str, Any] = {}
        if source_type:
            enrichment["source_type"] = source_type
        if created_at is not None:
            enrichment["created_at"] = created_at.isoformat()

        if not humanized:
            from backend.pipeline.repo_resolver import resolve_from_path

            identity = resolve_from_path(file_path) if file_path else None
            humanized = identity.humanized if identity is not None else None
        if humanized:
            project_id = await self.get_or_create_project_by_name(humanized)
            enrichment["project_id"] = str(project_id)

        return enrichment

    async def delete_mining_results_by_type(
        self,
        transcript_id: uuid.UUID,
        miner_type: str,
    ) -> int:
        """Delete MiningResult rows of a specific miner type for one transcript.

        Used by per-miner tasks (e.g. knowledge_extract_task) so a retry
        never duplicates rows, without affecting other miners' output for
        the same transcript.

        Args:
            transcript_id: UUID of the transcript whose rows to delete.
            miner_type: Miner category to scope the delete to.

        Returns:
            Number of rows deleted.
        """
        result = await self.db.execute(
            delete(MiningResult).where(
                MiningResult.transcript_id == transcript_id,
                MiningResult.miner_type == miner_type,
            )
        )
        return int(result.rowcount or 0)

    async def delete_chunks(self, transcript_id: uuid.UUID) -> None:
        """Remove a transcript's chunks from Postgres and Qdrant.

        Used by the resume path so re-chunking a partially-processed transcript
        never leaves duplicate chunks behind.
        """
        chunk_rows = (
            await self.db.execute(
                select(Chunk.id).where(Chunk.transcript_id == transcript_id)
            )
        ).scalars().all()
        if chunk_rows and self.search is not None:
            try:
                await self.search.delete_chunks([str(cid) for cid in chunk_rows])
            except Exception:
                logger.exception("delete_chunks: Qdrant delete failed")
        await self.db.execute(
            delete(Chunk).where(Chunk.transcript_id == transcript_id)
        )

    async def update_transcript_status(
        self,
        transcript_id: uuid.UUID,
        status: str,
    ) -> None:
        """Update the processing status of a transcript.

        Args:
            transcript_id: UUID of the transcript to update.
            status: New status (``pending``, ``processing``, ``completed``, ``error``).
        """
        result = await self.db.execute(
            select(Transcript).where(Transcript.id == transcript_id)
        )
        transcript = result.scalar_one_or_none()
        if transcript is not None:
            transcript.status = status  # type: ignore[assignment]
            await self.db.flush()
            logger.info(
                "update_transcript_status: %s -> %s", transcript_id, status
            )

    async def source_exists(self, file_hash: str) -> bool:
        """Check whether a source with the given file hash already exists.

        Args:
            file_hash: SHA-256 hash of the file content.

        Returns:
            ``True`` if a matching source is found in the database.
        """
        result = await self.db.execute(
            select(Source).where(
                Source.metadata_["file_hash"].as_string() == file_hash
            )
        )
        return result.scalar_one_or_none() is not None

    # Normalise LLM-provided status/priority strings to the values the UI
    # (Kanban board, filters) expects, defaulting unknowns sensibly.
    _TASK_STATUS_MAP = {
        "todo": "todo",
        "pending": "todo",
        "not_started": "todo",
        "in_progress": "in_progress",
        "in-progress": "in_progress",
        "doing": "in_progress",
        "active": "in_progress",
        "done": "done",
        "completed": "done",
        "complete": "done",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "abandoned": "cancelled",
    }
    _PRIORITY_MAP = {
        "low": "low",
        "medium": "medium",
        "normal": "medium",
        "high": "high",
        "urgent": "high",
        "critical": "high",
    }

    async def store_mining_results(
        self,
        transcript_id: uuid.UUID,
        results: dict[str, Any],
    ) -> dict[str, int]:
        """Persist LLM mining output as Project/Task/Artifact/MiningResult rows.

        Projects are de-duplicated by name (get-or-create); tasks and
        artifacts are linked to the transcript's primary project when one was
        extracted. The raw per-miner output is also stored as MiningResult
        rows for traceability.

        Args:
            transcript_id: UUID of the mined transcript.
            results: Output of ``MiningEngine.mine_transcript``.

        Returns:
            Counts of rows created, keyed by entity type.
        """
        counts = {"projects": 0, "tasks": 0, "artifacts": 0, "mining_results": 0}

        # Idempotency: clear this transcript's prior mining output before
        # re-inserting, so re-mining (e.g. after an LLM outage produced empty
        # results) never duplicates tasks/artifacts/mining rows. Projects are
        # shared across transcripts (deduped by name), so they are left intact.
        # Knowledge-base atoms use their own miner_type and are wiped by
        # knowledge_extract_task's own idempotency path; never delete them
        # here or a re-run of mine_task would clobber the KB feed.
        await self.db.execute(
            delete(Task).where(Task.source_transcript_id == transcript_id)
        )
        await self.db.execute(
            delete(Artifact).where(Artifact.source_transcript_id == transcript_id)
        )
        await self.db.execute(
            delete(MiningResult).where(
                MiningResult.transcript_id == transcript_id,
                MiningResult.miner_type != "knowledge",
            )
        )

        # --- Projects (get-or-create by name) ---
        project_ids: dict[str, uuid.UUID] = {}
        # Tracks rows this transcript created so the empty-project sweep
        # at the end only nukes rows nobody else attached anything to.
        newly_created_project_ids: set[uuid.UUID] = set()
        for proj_data in results.get("projects", []):
            name = (proj_data.get("name") or "").strip()
            if not name:
                continue
            if name in project_ids:
                continue
            existing = (
                await self.db.execute(select(Project).where(Project.name == name))
            ).scalar_one_or_none()
            if existing is not None:
                project_ids[name] = existing.id  # type: ignore[assignment]
                continue
            project = Project(
                name=name,
                description=proj_data.get("description"),
                status=proj_data.get("status") or "active",
                metadata_={"confidence": proj_data.get("confidence")},
            )
            # SAVEPOINT-scoped insert: if a parallel mine_task wins the race
            # on the UNIQUE(name) constraint, only THIS statement rolls back,
            # not the outer transaction (which holds earlier work in this
            # store_mining_results call).
            try:
                async with self.db.begin_nested():
                    self.db.add(project)
                    await self.db.flush()
            except IntegrityError:
                existing = (
                    await self.db.execute(
                        select(Project).where(Project.name == name)
                    )
                ).scalar_one()
                project_ids[name] = existing.id  # type: ignore[assignment]
                continue
            project_ids[name] = project.id  # type: ignore[assignment]
            newly_created_project_ids.add(project.id)  # type: ignore[arg-type]
            counts["projects"] += 1

        primary_project_id = next(iter(project_ids.values()), None)

        # --- Tasks ---
        _STATUS_RANK = {"done": 3, "cancelled": 2, "in_progress": 1, "todo": 0}

        for task_data in results.get("tasks", []):
            title = (task_data.get("title") or "").strip()
            if not title:
                continue
            inferred_status = self._TASK_STATUS_MAP.get(
                str(task_data.get("status", "")).lower(), "todo"
            )
            inferred_priority = self._PRIORITY_MAP.get(
                str(task_data.get("priority", "")).lower(), "medium"
            )

            existing = (
                await self.db.execute(
                    select(Task).where(
                        Task.project_id == primary_project_id,
                        Task.title == title,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                current_rank = _STATUS_RANK.get(existing.status, 0)
                inferred_rank = _STATUS_RANK.get(inferred_status, 0)
                if inferred_rank > current_rank:
                    existing.status = inferred_status
                    existing.description = task_data.get("description") or existing.description
                if not existing.source_transcript_id:
                    existing.source_transcript_id = transcript_id
            else:
                self.db.add(
                    Task(
                        project_id=primary_project_id,
                        title=title,
                        description=task_data.get("description"),
                        status=inferred_status,
                        priority=inferred_priority,
                        source_transcript_id=transcript_id,
                        metadata_={"confidence": task_data.get("confidence")},
                    )
                )
            counts["tasks"] += 1

        # --- Artifacts (high-level deliverables only) ---
        for art_data in results.get("artifacts", []):
            name = (art_data.get("name") or "").strip()
            if not name:
                continue

            artifact_type = str(art_data.get("type") or "").lower().strip()
            if artifact_type not in ARTIFACT_TYPES:
                continue

            confidence = art_data.get("confidence")
            if isinstance(confidence, (int, float)) and confidence < 0.6:
                continue

            url = str(art_data.get("url", "")).strip() if artifact_type == "link" else ""
            if artifact_type == "link" and not url:
                continue

            tags = list(art_data.get("tags") or [])
            if "high-level" not in tags:
                tags.append("high-level")

            self.db.add(
                Artifact(
                    project_id=primary_project_id,
                    artifact_type=artifact_type,
                    name=name,
                    content={
                        "language": art_data.get("language"),
                        "content_preview": art_data.get("content_preview"),
                        "file_path": art_data.get("file_path"),
                        "url": url,
                        "significance": art_data.get("significance"),
                    },
                    source_transcript_id=transcript_id,
                    tags=tags,
                    metadata_={"confidence": confidence},
                )
            )
            counts["artifacts"] += 1

        # --- Raw per-miner results (traceability) ---
        status_block = results.get("status", {}) or {}
        miner_payloads: dict[str, dict[str, Any]] = {
            "projects": {"items": results.get("projects", [])},
            "tasks": {"items": results.get("tasks", [])},
            "status": status_block,
            "artifacts": {"items": results.get("artifacts", [])},
            "missing_elements": {"items": results.get("missing_elements", [])},
            "abandoned_work": results.get("abandoned_work", {}) or {},
        }
        for miner_type, payload in miner_payloads.items():
            confidence = payload.get("confidence")
            self.db.add(
                MiningResult(
                    transcript_id=transcript_id,
                    miner_type=miner_type,
                    result_data=payload,
                    confidence=(
                        float(confidence)
                        if isinstance(confidence, (int, float))
                        else None
                    ),
                    metadata_={},
                )
            )
            counts["mining_results"] += 1

        await self.db.flush()

        # Concurrency-safe empty-project sweep: only delete projects this
        # transcript just created, and only when nobody — including a
        # parallel mine_task — has attached a task or artifact to them.
        # The NOT EXISTS guard prevents racing workers from cascading
        # each other's tasks away.
        if newly_created_project_ids:
            dropped = await self.db.execute(
                delete(Project).where(
                    Project.id.in_(newly_created_project_ids),
                    ~exists().where(Task.project_id == Project.id),
                    ~exists().where(Artifact.project_id == Project.id),
                )
            )
            n_dropped = dropped.rowcount or 0
            if n_dropped:
                counts["projects"] -= n_dropped
                counts["projects_dropped_empty"] = n_dropped

        logger.info(
            "store_mining_results: %s -> %d projects, %d tasks, %d artifacts",
            transcript_id,
            counts["projects"],
            counts["tasks"],
            counts["artifacts"],
        )
        return counts

    async def get_transcript_text(self, transcript_id: uuid.UUID) -> str:
        """Fetch the full concatenated text of a transcript.

        Args:
            transcript_id: UUID of the transcript.

        Returns:
            Concatenated message content, or ``raw_text`` if no messages.
        """
        result = await self.db.execute(
            select(Transcript).where(Transcript.id == transcript_id)
        )
        transcript = result.scalar_one_or_none()
        if transcript is None:
            return ""

        if transcript.raw_text:
            return transcript.raw_text  # type: ignore[return-value]

        # Fallback: concatenate messages
        result = await self.db.execute(
            select(Message)
            .where(Message.transcript_id == transcript_id)
            .order_by(Message.sequence)
        )
        messages = result.scalars().all()
        return "\n".join(
            f"{m.speaker or 'unknown'}: {m.content}" for m in messages
        )
