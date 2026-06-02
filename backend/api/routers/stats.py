"""API router for Stats endpoints.

Provides detailed statistics beyond the basic /api/v1/stats endpoint,
including trends, breakdowns, and time-series data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
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
from backend.core.schemas import StatsResponse

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/detailed")
async def get_detailed_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get detailed platform statistics with breakdowns.

    Args:
        db: Async database session.

    Returns:
        Detailed statistics dict with counts, status breakdowns,
        and recent activity.
    """
    # Basic counts
    sources_count = await _count_model(db, Source)
    transcripts_count = await _count_model(db, Transcript)
    projects_count = await _count_model(db, Project)
    tasks_count = await _count_model(db, Task)
    artifacts_count = await _count_model(db, Artifact)
    messages_count = await _count_model(db, Message)
    mining_results_count = await _count_model(db, MiningResult)

    # Transcript status breakdown
    status_result = await db.execute(
        select(Transcript.status, func.count(Transcript.id)).group_by(Transcript.status)
    )
    transcript_statuses = {s: c for s, c in status_result.all()}

    # Task status breakdown
    task_status_result = await db.execute(
        select(Task.status, func.count(Task.id)).group_by(Task.status)
    )
    task_statuses = {s: c for s, c in task_status_result.all()}

    # Source type breakdown
    source_type_result = await db.execute(
        select(Source.source_type, func.count(Source.id)).group_by(Source.source_type)
    )
    source_types = {t: c for t, c in source_type_result.all()}

    # Recent activity (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_sources = await _count_model_since(db, Source, week_ago)
    recent_transcripts = await _count_model_since(db, Transcript, week_ago)
    recent_tasks = await _count_model_since(db, Task, week_ago)

    return {
        "counts": {
            "sources": sources_count,
            "transcripts": transcripts_count,
            "projects": projects_count,
            "tasks": tasks_count,
            "artifacts": artifacts_count,
            "messages": messages_count,
            "mining_results": mining_results_count,
        },
        "breakdowns": {
            "transcript_status": transcript_statuses,
            "task_status": task_statuses,
            "source_type": source_types,
        },
        "recent_activity_7d": {
            "new_sources": recent_sources,
            "new_transcripts": recent_transcripts,
            "new_tasks": recent_tasks,
        },
    }


@router.get("/trends")
async def get_trends(
    db: AsyncSession = Depends(get_db),
    days: int = 30,
) -> dict[str, list[dict[str, Any]]]:
    """Get daily creation trends for the past N days.

    Args:
        db: Async database session.
        days: Number of days to look back.

    Returns:
        Dict with daily counts for transcripts, tasks, and sources.
    """
    from datetime import date

    cutoff = datetime.utcnow() - timedelta(days=days)

    # Get daily transcript counts
    transcript_result = await db.execute(
        select(
            func.date(Transcript.created_at).label("day"),
            func.count(Transcript.id).label("count"),
        )
        .where(Transcript.created_at >= cutoff)
        .group_by(func.date(Transcript.created_at))
        .order_by(func.date(Transcript.created_at))
    )
    transcript_trends = [
        {"date": str(day), "count": count} for day, count in transcript_result.all()
    ]

    # Get daily task counts
    task_result = await db.execute(
        select(
            func.date(Task.created_at).label("day"),
            func.count(Task.id).label("count"),
        )
        .where(Task.created_at >= cutoff)
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at))
    )
    task_trends = [
        {"date": str(day), "count": count} for day, count in task_result.all()
    ]

    # Get daily source counts
    source_result = await db.execute(
        select(
            func.date(Source.created_at).label("day"),
            func.count(Source.id).label("count"),
        )
        .where(Source.created_at >= cutoff)
        .group_by(func.date(Source.created_at))
        .order_by(func.date(Source.created_at))
    )
    source_trends = [
        {"date": str(day), "count": count} for day, count in source_result.all()
    ]

    return {
        "transcripts": transcript_trends,
        "tasks": task_trends,
        "sources": source_trends,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _count_model(db: AsyncSession, model: type) -> int:
    """Count all rows in a model."""
    result = await db.execute(select(func.count(model.id)))
    return result.scalar() or 0


async def _count_model_since(db: AsyncSession, model: type, since: datetime) -> int:
    """Count rows created since a given datetime."""
    result = await db.execute(
        select(func.count(model.id)).where(model.created_at >= since)
    )
    return result.scalar() or 0
