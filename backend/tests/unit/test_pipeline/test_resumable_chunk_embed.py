"""Tests for resumable, budget-bounded chunk embedding.

Covers the storage primitives that let ``chunk_embed_task`` persist unembedded
chunk shells, embed them in bounded batches, and continue after a worker
kill, so a huge transcript never exceeds the 1-hour ``task_time_limit``.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable, Awaitable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Chunk, Source, Transcript
from backend.pipeline.storage import PipelineStorage

VEC = 768


def _vec(*vals: float) -> list[float]:
    """Return a 768-dim vector, padding with the first value (or 0.0)."""
    if not vals:
        return [0.0] * VEC
    return [vals[0]] * VEC


@pytest_asyncio.fixture
async def storage(db_session: AsyncSession) -> PipelineStorage:
    """Build a PipelineStorage bound to the rolled-back test session."""
    return PipelineStorage(db=db_session, search_engine=None)


async def _new_transcript(db: AsyncSession) -> uuid.UUID:
    """Create a real Source + Transcript so chunk FK constraints are met."""
    source = Source(source_type="claude")
    db.add(source)
    await db.flush()
    transcript = Transcript(source_id=source.id)
    db.add(transcript)
    await db.flush()
    return transcript.id


@pytest.mark.asyncio
async def test_store_chunk_shells_persists_without_embedding(db_session, storage) -> None:
    """Storing shells records text/metadata with embedding NULL so the embedder
    can be resumed later."""
    transcript_id = await _new_transcript(db_session)
    await storage.store_chunk_shells(
        transcript_id,
        [
            {"text": "alpha", "metadata": {"transcript_id": str(transcript_id)}},
            {"text": "beta", "metadata": {"transcript_id": str(transcript_id)}},
        ],
    )

    rows = await storage.load_unembedded_chunks(transcript_id, limit=10)
    assert [r[1] for r in rows] == ["alpha", "beta"]
    # embeddings must be untouched (None) so a later step fills them
    all_rows = await storage.count_unembedded(transcript_id)
    assert all_rows == 2


@pytest.mark.asyncio
async def test_load_unembedded_chunks_respects_limit_and_order(db_session, storage) -> None:
    """Unembedded chunks load oldest-first and bounded by ``limit``."""
    transcript_id = await _new_transcript(db_session)
    await storage.store_chunk_shells(
        transcript_id,
        [{"text": f"c{i}", "metadata": {}} for i in range(5)],
    )

    first = await storage.load_unembedded_chunks(transcript_id, limit=2)
    assert [r[1] for r in first] == ["c0", "c1"]


@pytest.mark.asyncio
async def test_update_chunk_embeddings_fills_only_matching(db_session, storage) -> None:
    """Writing embeddings stamps the given chunks and drops them from the
    unembedded queue."""
    transcript_id = await _new_transcript(db_session)
    stored_ids = await storage.store_chunk_shells(
        transcript_id,
        [{"text": f"c{i}", "metadata": {}} for i in range(3)],
    )

    embedding_map = {stored_ids[0]: _vec(0.1), stored_ids[1]: _vec(0.3)}
    await storage.update_chunk_embeddings(transcript_id, embedding_map)

    remaining = await storage.load_unembedded_chunks(transcript_id, limit=10)
    assert [r[1] for r in remaining] == ["c2"]


@pytest.mark.asyncio
async def test_embed_chunks_budgeted_returns_when_budget_exhausted(db_session, storage) -> None:
    """The budgeted embedder persists a batch and reports it exhausted the
    budget so the caller can re-dispatch instead of blocking past the limit."""
    transcript_id = await _new_transcript(db_session)
    await storage.store_chunk_shells(
        transcript_id,
        [{"text": f"c{i}", "metadata": {}} for i in range(50)],
    )
    batch_size = 5  # 10 batches total

    def embed_batch(texts: list[str]) -> list[list[float]]:
        time.sleep(0.005)  # 5ms per batch -> 50ms if run to completion
        return [_vec(float(i)) for i in range(len(texts))]

    started = time.monotonic()
    exhausted, done = await storage.embed_chunks_budgeted(
        transcript_id,
        embed_batch=embed_batch,
        batch_size=batch_size,
        time_budget_ns=20 * 1_000_000,  # 20ms -> exhaust after ~4 batches
    )
    elapsed = time.monotonic() - started

    assert exhausted is True
    assert 0 < done < 50
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_embed_chunks_budgeted_completes_under_budget(db_session, storage) -> None:
    """When work fits comfortably in the budget the embedder drains the queue
    and reports not-exhausted."""
    transcript_id = await _new_transcript(db_session)
    stored_ids = await storage.store_chunk_shells(
        transcript_id,
        [{"text": f"c{i}", "metadata": {}} for i in range(6)],
    )
    batch_size = 50  # single huge batch fits all in one call

    def embed_batch(texts: list[str]) -> list[list[float]]:
        return [_vec(float(i)) for i in range(len(texts))]

    exhausted, done = await storage.embed_chunks_budgeted(
        transcript_id,
        embed_batch=embed_batch,
        batch_size=batch_size,
        time_budget_ns=60 * 1_000_000_000,
    )

    assert exhausted is False
    assert done == 6
    assert await storage.count_unembedded(transcript_id) == 0


@pytest.mark.asyncio
async def test_count_chunks_tracks_shells_even_unembedded(db_session, storage) -> None:
    """Total chunk count includes both embedded and pending shells, so the
    resume path can tell "nothing chunked yet" from "partially embedded"."""
    transcript_id = await _new_transcript(db_session)
    assert await storage.count_chunks(transcript_id) == 0

    await storage.store_chunk_shells(
        transcript_id,
        [{"text": f"c{i}", "metadata": {}} for i in range(4)],
    )
    assert await storage.count_chunks(transcript_id) == 4


class _FakeSearch:
    """Minimal search engine stub that records indexed chunks."""

    def __init__(self) -> None:
        self.indexed: list[list[dict]] = []

    async def index_chunks(self, chunks: list[dict]) -> None:
        self.indexed.append(chunks)


@pytest.mark.asyncio
async def test_index_transcript_chunks_upserts_only_embedded(db_session) -> None:
    """Only fully-embedded chunks are indexed into the vector store, so a
    partially-embedded transcript is never partially searchable as complete."""
    transcript_id = await _new_transcript(db_session)
    search = _FakeSearch()
    storage = PipelineStorage(db=db_session, search_engine=search)
    stored_ids = await storage.store_chunk_shells(
        transcript_id,
        [{"text": f"c{i}", "metadata": {}} for i in range(3)],
    )
    # Embed two of the three so one remains behind.
    await storage.update_chunk_embeddings(
        transcript_id,
        {
            stored_ids[0]: _vec(0.1),
            stored_ids[2]: _vec(0.5),
        },
    )

    count = await storage.index_transcript_chunks(transcript_id)

    assert count == 2
    assert len(search.indexed) == 1
    indexed_texts = [c["text"] for c in search.indexed[0]]
    assert indexed_texts == ["c0", "c2"]
    # Unembedded chunk is not indexed.
    assert all(c["text"] != "c1" for c in search.indexed[0])
    # Each indexed point carries a 768-dim vector.
    for chunk in search.indexed[0]:
        assert len(chunk["embedding"]) == VEC


@pytest.mark.asyncio
async def test_index_transcript_chunks_backfills_missing_enrichment(db_session) -> None:
    """Legacy chunks without project/source metadata are backfilled on reindex,
    so re-established transcripts satisfy the Qdrant filter contract."""
    source = Source(source_type="claude", metadata_={})  # no file_path
    db_session.add(source)
    await db_session.flush()
    transcript_id = uuid.uuid4()
    transcript = Transcript(id=transcript_id, source_id=source.id)
    db_session.add(transcript)
    await db_session.flush()

    search = _FakeSearch()
    storage = PipelineStorage(db=db_session, search_engine=search)
    stored_ids = await storage.store_chunk_shells(
        transcript_id,
        [{"text": "legacy", "metadata": {"transcript_id": str(transcript_id)}}],
    )
    await storage.update_chunk_embeddings(transcript_id, {stored_ids[0]: _vec(0.7)})

    count = await storage.index_transcript_chunks(transcript_id)

    assert count == 1
    indexed_meta = search.indexed[0][0]["metadata"]
    # No resolvable project, but source context is stamped back.
    assert indexed_meta["source_type"] == "claude"
    assert "project_id" not in indexed_meta
    # PostgreSQL source of truth agrees with what was indexed.
    from sqlalchemy import select as sa_select

    chunk_row = (
        await db_session.execute(
            sa_select(Chunk).where(Chunk.id == stored_ids[0])
        )
    ).scalar_one()
    assert chunk_row.metadata_["source_type"] == "claude"