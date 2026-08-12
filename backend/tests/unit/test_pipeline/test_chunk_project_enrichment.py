"""Tests for stamping project/source metadata onto chunk rows.

The Qdrant filter for ``project_id`` (backend/search/engine.py::_build_filter)
matches ``metadata.project_id``. Without injection at chunk time that filter is
a dead match, so large transcripts never surface under a project scope. These
tests cover the storage helpers that let ``chunk_embed_task`` stamp it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Chunk, Project, Source, Transcript
from backend.pipeline.storage import PipelineStorage

HUMANIZED = "faker/some-repo"


@pytest_asyncio.fixture
async def storage(db_session: AsyncSession) -> PipelineStorage:
    """Build a PipelineStorage bound to the rolled-back test session."""
    return PipelineStorage(db=db_session, search_engine=None)


async def _new_transcript(
    db: AsyncSession, *, py: str = "python", source_type: str = "claude"
) -> tuple[uuid.UUID, uuid.UUID]:
    source = Source(source_type=source_type, metadata_={"file_path": f"/tmp/repo/{py}/main.py"})
    db.add(source)
    await db.flush()
    transcript = Transcript(source_id=source.id)
    db.add(transcript)
    await db.flush()
    return transcript.id, source.id


@pytest.mark.asyncio
async def test_get_or_create_project_by_name_is_idempotent(db_session, storage) -> None:
    """The same humanized name maps to one stable project id."""
    first = await storage.get_or_create_project_by_name(HUMANIZED)
    second = await storage.get_or_create_project_by_name(HUMANIZED)

    assert first == second
    from sqlalchemy import func

    count = (
        await db_session.execute(
            select(func.count()).select_from(Project).where(Project.name == HUMANIZED)
        )
    ).scalar_one()
    # Project row exists exactly once.
    assert count == 1


@pytest.mark.asyncio
async def test_get_chunk_enrichment_stamps_project_and_source(db_session, storage) -> None:
    """Enrichment carries a stable project_id plus source_type and created_at
    so every chunk matching the transcript is findable under those filters."""
    transcript_id, _ = await _new_transcript(db_session)

    meta = await storage.get_chunk_enrichment(transcript_id, humanized=HUMANIZED)

    assert "project_id" in meta
    assert meta["source_type"] == "claude"
    assert meta["created_at"]  # non-empty ISO timestamp
    # project_id is a valid UUID string for the Project we just created.
    proj = (
        await db_session.execute(select(Project).where(Project.name == HUMANIZED))
    ).scalar_one()
    assert uuid.UUID(meta["project_id"]) == proj.id


@pytest.mark.asyncio
async def test_get_chunk_enrichment_without_project_identity(db_session, storage) -> None:
    """A transcript whose source has no resolvable path still yields harmless
    source metadata, never a crash or missing key access."""
    source = Source(
        source_type="claude",
        metadata_={},  # no file_path -> no project identity
    )
    db_session.add(source)
    await db_session.flush()
    transcript = Transcript(source_id=source.id)
    db_session.add(transcript)
    await db_session.flush()

    meta = await storage.get_chunk_enrichment(transcript.id)

    assert "source_type" in meta
    assert "created_at" in meta
    assert "project_id" not in meta


@pytest.mark.asyncio
async def test_store_chunk_shells_merges_enrichment(db_session, storage) -> None:
    """Chunk shells store the enriched metadata dict verbatim."""
    transcript_id, _ = await _new_transcript(db_session)
    enrichment = await storage.get_chunk_enrichment(transcript_id, humanized=HUMANIZED)

    await storage.store_chunk_shells(
        transcript_id,
        [{"text": "alpha", "metadata": {"transcript_id": str(transcript_id)}}],
        enrichment=enrichment,
    )

    chunk = (
        await db_session.execute(
            select(Chunk).where(Chunk.transcript_id == transcript_id)
        )
    ).scalar_one()
    assert chunk.metadata_["transcript_id"] == str(transcript_id)
    assert chunk.metadata_["project_id"] == enrichment["project_id"]
    assert chunk.metadata_["source_type"] == "claude"