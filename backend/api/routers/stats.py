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


@router.get("/weekly-summary")
async def get_weekly_summary(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a 'last week' summary for the dashboard.

    Buckets:
    - done: tasks marked done and updated in the last 7 days, plus artifacts
      created in the last 7 days.
    - in_progress: tasks currently in_progress and updated in the last 7 days.
    - stale: tasks still todo/in_progress but not touched in the last 7 days.

    Args:
        db: Async database session.

    Returns:
        Dict with counts and top items for each bucket.
    """
    week_ago = datetime.utcnow() - timedelta(days=7)

    # Project name map for display.
    project_result = await db.execute(select(Project.id, Project.name))
    project_names: dict[Any, str] = {r.id: r.name for r in project_result.all()}

    # Done this week (tasks moved/completed to done + new artifacts).
    done_tasks_result = await db.execute(
        select(Task)
        .where(Task.status == "done", Task.updated_at >= week_ago)
        .order_by(Task.updated_at.desc())
        .limit(10)
    )
    done_tasks = list(done_tasks_result.scalars().all())

    recent_artifacts_result = await db.execute(
        select(Artifact)
        .where(Artifact.created_at >= week_ago)
        .order_by(Artifact.created_at.desc())
        .limit(10)
    )
    recent_artifacts = list(recent_artifacts_result.scalars().all())

    done_items = [
        {
            "id": str(t.id),
            "kind": "task",
            "title": t.title,
            "project_id": str(t.project_id) if t.project_id else None,
            "project_name": project_names.get(t.project_id),
            "status": t.status,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in done_tasks
    ] + [
        {
            "id": str(a.id),
            "kind": "artifact",
            "title": a.name,
            "project_id": str(a.project_id) if a.project_id else None,
            "project_name": project_names.get(a.project_id),
            "artifact_type": a.artifact_type,
            "updated_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in recent_artifacts
    ]

    # In progress this week.
    in_progress_result = await db.execute(
        select(Task)
        .where(Task.status == "in_progress", Task.updated_at >= week_ago)
        .order_by(Task.updated_at.desc())
        .limit(10)
    )
    in_progress_tasks = list(in_progress_result.scalars().all())
    in_progress_items = [
        {
            "id": str(t.id),
            "kind": "task",
            "title": t.title,
            "project_id": str(t.project_id) if t.project_id else None,
            "project_name": project_names.get(t.project_id),
            "status": t.status,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in in_progress_tasks
    ]

    # Stale: todo or in_progress but not updated this week.
    stale_result = await db.execute(
        select(Task)
        .where(
            Task.status.in_(["todo", "in_progress"]),
            Task.updated_at < week_ago,
        )
        .order_by(Task.updated_at.asc())
        .limit(10)
    )
    stale_tasks = list(stale_result.scalars().all())
    stale_items = [
        {
            "id": str(t.id),
            "kind": "task",
            "title": t.title,
            "project_id": str(t.project_id) if t.project_id else None,
            "project_name": project_names.get(t.project_id),
            "status": t.status,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in stale_tasks
    ]

    return {
        "since": week_ago.isoformat(),
        "done": {"count": len(done_items), "items": done_items},
        "in_progress": {"count": len(in_progress_items), "items": in_progress_items},
        "stale": {"count": len(stale_items), "items": stale_items},
    }


@router.get("/resolver")
async def get_resolver_stats() -> dict[str, Any]:
    """Return repo-resolver counters and unmatched-slug curation hints.

    Counters are process-local. With multiple worker processes the worker
    that receives the HTTP request reports only its own counters — useful as
    a smoke signal, not a precise total.
    """
    from backend.pipeline.repo_resolver import counters, unmatched_slugs

    return {
        "counters": counters(),
        "unmatched_top": [
            {"slug": s, "count": c} for s, c in unmatched_slugs(top_n=50)
        ],
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
