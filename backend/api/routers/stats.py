"""API router for Stats endpoints.

Provides detailed statistics beyond the basic /api/v1/stats endpoint,
including trends, breakdowns, and time-series data.
"""

from __future__ import annotations

import json
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
    """Get an LLM-generated narrative summary of recent and at-risk work.

    Args:
        db: Async database session.

    Returns:
        Dict with a single ``summary`` key containing the generated text.
    """
    from backend.mining.engine import MiningEngine

    # Project name map.
    project_result = await db.execute(select(Project.id, Project.name))
    project_names: dict[Any, str] = {r.id: r.name for r in project_result.all()}

    # Load all tasks, artifacts, and transcripts for project-level aggregation.
    # Personal-scale data; revisit if this becomes a bottleneck.
    all_tasks = (await db.execute(select(Task))).scalars().all()
    all_artifacts = (await db.execute(select(Artifact))).scalars().all()
    all_transcripts = (await db.execute(select(Transcript))).scalars().all()

    tasks_by_project: dict[Any, list[Task]] = {}
    for t in all_tasks:
        tasks_by_project.setdefault(t.project_id, []).append(t)

    artifacts_by_project: dict[Any, list[Artifact]] = {}
    for a in all_artifacts:
        artifacts_by_project.setdefault(a.project_id, []).append(a)

    transcripts_by_project: dict[Any, list[Transcript]] = {}
    for tr in all_transcripts:
        project_name = (tr.metadata_ or {}).get("project_name")
        if project_name:
            for pid, name in project_names.items():
                if name == project_name:
                    transcripts_by_project.setdefault(pid, []).append(tr)
                    break

    # Build per-project activity snapshots.
    project_snapshots = []
    projects = (await db.execute(select(Project))).scalars().all()
    for p in projects:
        tasks = tasks_by_project.get(p.id, [])
        artifacts = artifacts_by_project.get(p.id, [])
        transcripts = transcripts_by_project.get(p.id, [])

        last_task_update = max(
            (t.updated_at for t in tasks if t.updated_at), default=None
        )
        last_artifact = max(
            (a.created_at for a in artifacts if a.created_at), default=None
        )
        last_transcript = max(
            (tr.created_at for tr in transcripts if tr.created_at), default=None
        )
        last_activity = max(
            [p.updated_at, last_task_update, last_artifact, last_transcript],
            default=None,
        )

        todo_tasks = [t for t in tasks if t.status == "todo"]
        in_progress_tasks = [t for t in tasks if t.status == "in_progress"]
        done_tasks = [t for t in tasks if t.status == "done"]
        cancelled_tasks = [t for t in tasks if t.status == "cancelled"]

        # Skip projects with no activity and no work items.
        if not tasks and not artifacts and not transcripts:
            continue

        project_snapshots.append({
            "name": p.name,
            "status": p.status,
            "last_activity": last_activity.isoformat() if last_activity else None,
            "task_counts": {
                "todo": len(todo_tasks),
                "in_progress": len(in_progress_tasks),
                "done": len(done_tasks),
                "cancelled": len(cancelled_tasks),
            },
            "unfinished_tasks": [
                {
                    "title": t.title,
                    "status": t.status,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in sorted(
                    todo_tasks + in_progress_tasks,
                    key=lambda x: x.updated_at or datetime.min,
                )[:10]
            ],
            "recent_artifacts": [
                {"name": a.name, "type": a.artifact_type}
                for a in sorted(
                    artifacts,
                    key=lambda x: x.created_at or datetime.min,
                    reverse=True,
                )[:5]
            ],
            "recent_transcripts": [
                {"title": tr.title, "status": tr.status}
                for tr in sorted(
                    transcripts,
                    key=lambda x: x.created_at or datetime.min,
                    reverse=True,
                )[:5]
            ],
        })

    # Sort by last activity, most recent first.
    project_snapshots.sort(
        key=lambda x: (x["last_activity"] or "",),
        reverse=True,
    )

    context = {
        "report_date": datetime.utcnow().isoformat(),
        "lookback_days": 30,
        "total_projects": len(projects),
        "total_incomplete_tasks": sum(
            p["task_counts"]["todo"] + p["task_counts"]["in_progress"]
            for p in project_snapshots
        ),
        "projects": project_snapshots[:30],
    }

    engine = MiningEngine()
    summary = await engine.generate_weekly_summary(json.dumps(context, default=str))

    return {"summary": summary}


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
