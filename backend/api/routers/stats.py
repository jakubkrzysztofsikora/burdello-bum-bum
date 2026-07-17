"""API router for Stats endpoints.

Provides detailed statistics beyond the basic /api/v1/stats endpoint,
including trends, breakdowns, and time-series data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from redis.asyncio import Redis, from_url
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.database import AsyncSessionLocal, get_db
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
logger = logging.getLogger(__name__)

_WEEKLY_SUMMARY_KEY = "weekly_summary"
_WEEKLY_SUMMARY_FRESH_TTL = 3600  # 1 hour
_WEEKLY_SUMMARY_STALE_TTL = 86400  # 24 hours


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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get an LLM-generated narrative summary of recent and at-risk work.

    The result is cached in Redis for one hour. A stale copy is kept for 24
    hours and refreshed in the background, so the dashboard always returns
    instantly even if the LLM is slow.

    Args:
        background_tasks: FastAPI background task runner.
        db: Async database session.

    Returns:
        Dict with a ``summary`` key and optional ``stale`` flag.
    """
    redis = _get_redis()
    try:
        cached = await _get_cached_summary(redis)
        if cached is not None and not cached.get("stale"):
            return {"summary": cached["summary"], "stale": False}

        # If we have a stale copy, return it immediately and regenerate later.
        if cached is not None and cached.get("stale"):
            background_tasks.add_task(_regenerate_and_cache_summary, redis)
            return {"summary": cached["summary"], "stale": True}

        # No cache: generate synchronously (user is waiting).
        summary = await _build_and_generate_summary(db)
        await _set_cached_summary(redis, summary)
        return {"summary": summary, "stale": False}
    finally:
        if redis is not None:
            await redis.close()


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


async def _build_and_generate_summary(db: AsyncSession) -> str:
    """Aggregate project data and ask the LLM for a narrative summary.

    Args:
        db: Async database session.

    Returns:
        Generated summary text.
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
            [v for v in (p.updated_at, last_task_update, last_artifact, last_transcript) if v is not None],
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
                )[:5]
            ],
            "recent_artifact_names": [
                a.name
                for a in sorted(
                    artifacts,
                    key=lambda x: x.created_at or datetime.min,
                    reverse=True,
                )[:3]
            ],
            "recent_transcript_titles": [
                tr.title
                for tr in sorted(
                    transcripts,
                    key=lambda x: x.created_at or datetime.min,
                    reverse=True,
                )[:3]
            ],
        })

    # Sort by last activity, most recent first.
    project_snapshots.sort(
        key=lambda x: (x["last_activity"] or ""),
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
        "projects": project_snapshots[:15],
    }

    engine = MiningEngine()
    return await engine.generate_weekly_summary(
        json.dumps(context, default=str),
        timeout=90,
    )


async def _regenerate_and_cache_summary(redis: Redis | None) -> None:
    """Refresh the cached summary in the background.

    Args:
        redis: Optional Redis client.
    """
    if redis is None:
        return
    try:
        async with AsyncSessionLocal() as db:
            summary = await _build_and_generate_summary(db)
            await _set_cached_summary(redis, summary)
    except Exception:
        logger.exception("Background weekly-summary refresh failed")
    finally:
        await redis.close()


def _get_redis() -> Redis | None:
    """Create a Redis client, or None if Redis is not configured.

    Returns:
        An async Redis client, or None on failure.
    """
    try:
        return from_url(
            get_settings().REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception:
        logger.warning("Could not connect to Redis; weekly summary will not be cached")
        return None


async def _get_cached_summary(redis: Redis | None) -> dict[str, Any] | None:
    """Return the cached summary, marking it stale if it is older than the fresh TTL.

    Args:
        redis: Optional Redis client.

    Returns:
        Dict with ``summary`` and ``stale`` keys, or None if no cache entry.
    """
    if redis is None:
        return None
    try:
        raw = await redis.get(_WEEKLY_SUMMARY_KEY)
    except Exception:
        logger.warning("Redis get failed; treating weekly summary cache as missing")
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    generated_at_str = payload.get("generated_at")
    if not generated_at_str:
        return None

    try:
        generated_at = datetime.fromisoformat(generated_at_str)
    except ValueError:
        return None

    age_seconds = (datetime.utcnow() - generated_at).total_seconds()
    return {
        "summary": payload.get("summary", ""),
        "stale": age_seconds > _WEEKLY_SUMMARY_FRESH_TTL,
    }


async def _set_cached_summary(redis: Redis | None, summary: str) -> None:
    """Store the summary in Redis with the stale TTL.

    Args:
        redis: Optional Redis client.
        summary: Generated summary text.
    """
    if redis is None:
        return
    payload = {
        "summary": summary,
        "generated_at": datetime.utcnow().isoformat(),
    }
    try:
        await redis.set(
            _WEEKLY_SUMMARY_KEY,
            json.dumps(payload),
            ex=_WEEKLY_SUMMARY_STALE_TTL,
        )
    except Exception:
        logger.warning("Redis set failed; weekly summary will not be cached")


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
