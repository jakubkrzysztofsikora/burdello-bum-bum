"""Database and vector-store storage for processed transcripts.

Provides ``PipelineStorage`` which persists sources, transcripts, messages,
and chunks to PostgreSQL, and upserts chunk embeddings into Qdrant.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Chunk, Message, Source, Transcript
from backend.core.schemas import MessageCreate, TranscriptCreate
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
