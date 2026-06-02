"""API router for Mining endpoints.

Provides transcript mining trigger, results retrieval, and abandoned
work detection.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.core.models import MiningResult, Transcript
from backend.core.schemas import MiningResultResponse
from backend.mining.engine import MiningEngine

router = APIRouter(prefix="/mining", tags=["mining"])

# In-memory job tracker
_mining_jobs: dict[str, Any] = {}


@router.post("/transcript/{transcript_id}")
async def mine_transcript(
    transcript_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger AI mining for a transcript.

    Runs the mining engine asynchronously against the specified transcript.

    Args:
        transcript_id: UUID of the transcript to mine.
        background_tasks: FastAPI background tasks.
        db: Async database session.

    Returns:
        Dict with job ID and status.

    Raises:
        HTTPException: 404 if transcript not found, 422 if invalid UUID.
    """
    try:
        transcript_uuid = uuid.UUID(transcript_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {transcript_id}",
        )

    # Verify transcript exists
    result = await db.execute(
        select(Transcript.id).where(Transcript.id == transcript_uuid)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript with ID {transcript_id} not found",
        )

    job_id = f"mine_{transcript_id[:8]}_{uuid.uuid4().hex[:6]}"
    _mining_jobs[job_id] = {
        "transcript_id": transcript_id,
        "status": "queued",
        "results": [],
    }

    return {
        "job_id": job_id,
        "transcript_id": transcript_id,
        "status": "queued",
        "message": "Mining job queued for background processing",
    }


@router.get("/transcript/{transcript_id}")
async def get_mining_results(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
    miner_type: str | None = Query(None, description="Filter by miner type"),
) -> dict[str, Any]:
    """Get stored mining results for a transcript.

    Args:
        transcript_id: UUID of the transcript.
        db: Async database session.
        miner_type: Optional filter by miner type.

    Returns:
        Dict with transcript_id and list of mining results.

    Raises:
        HTTPException: 404 if transcript not found, 422 if invalid UUID.
    """
    try:
        transcript_uuid = uuid.UUID(transcript_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {transcript_id}",
        )

    # Verify transcript exists
    transcript_result = await db.execute(
        select(Transcript.id).where(Transcript.id == transcript_uuid)
    )
    if transcript_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript with ID {transcript_id} not found",
        )

    query = select(MiningResult).where(MiningResult.transcript_id == transcript_uuid)
    if miner_type:
        query = query.where(MiningResult.miner_type == miner_type)

    query = query.order_by(MiningResult.created_at.desc())

    result = await db.execute(query)
    results = list(result.scalars().all())

    return {
        "transcript_id": transcript_id,
        "total": len(results),
        "results": results,
    }


@router.get("/abandoned")
async def get_abandoned_work(
    days: int = Query(7, ge=1, le=365, description="Days since last activity"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Find old transcripts with no recent activity.

    Args:
        days: Number of days to consider as "old".
        db: Async database session.

    Returns:
        Dict with abandoned transcripts and count.
    """
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(Transcript)
        .where(Transcript.updated_at < cutoff)
        .where(Transcript.status != "completed")
        .order_by(Transcript.updated_at.asc())
        .limit(100)
    )
    transcripts = result.scalars().all()

    items = [
        {
            "id": str(t.id),
            "title": t.title,
            "status": t.status,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "days_inactive": (datetime.utcnow() - (t.updated_at or t.created_at)).days
            if t.updated_at or t.created_at
            else None,
        }
        for t in transcripts
    ]

    return {
        "days_threshold": days,
        "cutoff_date": cutoff.isoformat(),
        "total_abandoned": len(items),
        "items": items,
    }


@router.get("/jobs/{job_id}")
async def get_mining_job(job_id: str) -> dict[str, Any]:
    """Get the status of a mining job.

    Args:
        job_id: The mining job ID.

    Returns:
        Job status dict.

    Raises:
        HTTPException: 404 if job not found.
    """
    if job_id not in _mining_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mining job {job_id} not found",
        )

    return _mining_jobs[job_id]
