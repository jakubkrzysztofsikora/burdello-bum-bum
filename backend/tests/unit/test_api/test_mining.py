"""Tests for the Mining API router.

Covers mining trigger, results retrieval, abandoned work detection,
and job status endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Message, MiningResult, Source, Transcript


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_source(db: AsyncSession, title: str = "Test Source") -> Source:
    """Create a source for transcript tests."""
    source = Source(source_type="audio_file", title=title)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _create_transcript(
    db: AsyncSession,
    source: Source,
    title: str = "Test Transcript",
    status: str = "pending",
    **kwargs,
) -> Transcript:
    """Create a transcript in the database."""
    transcript = Transcript(
        source_id=source.id,
        title=title,
        status=status,
        metadata_=kwargs.get("metadata", {}),
    )
    db.add(transcript)
    await db.commit()
    await db.refresh(transcript)
    return transcript


async def _create_mining_result(
    db: AsyncSession,
    transcript: Transcript,
    miner_type: str = "topics",
    result_data: dict | None = None,
) -> MiningResult:
    """Create a mining result for a transcript."""
    result = MiningResult(
        transcript_id=transcript.id,
        miner_type=miner_type,
        result_data=result_data or {"topics": ["test"]},
        confidence=0.95,
    )
    db.add(result)
    await db.commit()
    await db.refresh(result)
    return result


# ---------------------------------------------------------------------------
# Mine Transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mine_transcript(client: AsyncClient, db_session: AsyncSession) -> None:
    """Triggering mining for a transcript queues a job."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source, title="Mine Me")

    response = await client.post(f"/api/v1/mining/transcript/{transcript.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["transcript_id"] == str(transcript.id)
    assert data["status"] == "queued"
    assert "job_id" in data


@pytest.mark.asyncio
async def test_mine_transcript_not_found(client: AsyncClient) -> None:
    """Mining a non-existent transcript returns 404."""
    random_id = uuid.uuid4()
    response = await client.post(f"/api/v1/mining/transcript/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mine_transcript_invalid_uuid(client: AsyncClient) -> None:
    """Mining with an invalid UUID returns 422."""
    response = await client.post("/api/v1/mining/transcript/invalid-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Get Mining Results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mining_results(client: AsyncClient, db_session: AsyncSession) -> None:
    """Getting mining results returns stored results."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source)
    await _create_mining_result(db_session, transcript, miner_type="topics")
    await _create_mining_result(db_session, transcript, miner_type="sentiment")

    response = await client.get(f"/api/v1/mining/transcript/{transcript.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["transcript_id"] == str(transcript.id)
    assert data["total"] == 2
    assert len(data["results"]) == 2


@pytest.mark.asyncio
async def test_get_mining_results_filtered(client: AsyncClient, db_session: AsyncSession) -> None:
    """Getting mining results with miner_type filter returns only matching."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source)
    await _create_mining_result(db_session, transcript, miner_type="topics")
    await _create_mining_result(db_session, transcript, miner_type="sentiment")

    response = await client.get(f"/api/v1/mining/transcript/{transcript.id}?miner_type=topics")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["results"][0]["miner_type"] == "topics"


@pytest.mark.asyncio
async def test_get_mining_results_not_found(client: AsyncClient) -> None:
    """Getting results for a non-existent transcript returns 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/mining/transcript/{random_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Abandoned Work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_abandoned_work(client: AsyncClient, db_session: AsyncSession) -> None:
    """Getting abandoned work returns old incomplete transcripts."""
    source = await _create_source(db_session)
    # Create an old transcript with pending status
    transcript = Transcript(
        source_id=source.id,
        title="Old Pending",
        status="pending",
        created_at=datetime.utcnow() - timedelta(days=10),
        updated_at=datetime.utcnow() - timedelta(days=10),
    )
    db_session.add(transcript)
    await db_session.commit()

    response = await client.get("/api/v1/mining/abandoned?days=7")
    assert response.status_code == 200

    data = response.json()
    assert data["days_threshold"] == 7
    assert data["total_abandoned"] >= 1


@pytest.mark.asyncio
async def test_get_abandoned_work_empty(client: AsyncClient) -> None:
    """Getting abandoned work with high threshold may return empty."""
    response = await client.get("/api/v1/mining/abandoned?days=365")
    assert response.status_code == 200

    data = response.json()
    assert "total_abandoned" in data
    assert "items" in data


# ---------------------------------------------------------------------------
# Mining Job Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mining_job_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """Getting a mining job status returns the job info."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source)

    # First trigger a job
    response = await client.post(f"/api/v1/mining/transcript/{transcript.id}")
    data = response.json()
    job_id = data["job_id"]

    # Now check status
    response = await client.get(f"/api/v1/mining/jobs/{job_id}")
    assert response.status_code == 200

    job_data = response.json()
    assert job_data["transcript_id"] == str(transcript.id)
    assert job_data["status"] == "queued"


@pytest.mark.asyncio
async def test_get_mining_job_not_found(client: AsyncClient) -> None:
    """Getting a non-existent job returns 404."""
    response = await client.get("/api/v1/mining/jobs/nonexistent_job")
    assert response.status_code == 404
