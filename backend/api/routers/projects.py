"""API router for Project endpoints.

Provides list, detail, and status update operations for projects
with filtering, searching, and computed statistics.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.core.models import Artifact, Project, Task, Transcript
from backend.core.schemas import (
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectStats,
    TaskSummary,
    ArtifactSummary,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="Filter by status (active, archived, deleted)"),
    search: str | None = Query(None, description="Search in project name"),
    sort: str = Query("last_activity_at", description="Sort field"),
    order: str = Query("desc", description="Sort order (asc|desc)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """List projects with optional status filter and text search.

    Args:
        db: Async database session.
        status: Optional status filter.
        search: Optional text search on project name.
        skip: Pagination offset.
        limit: Maximum items to return.

    Returns:
        Paginated list of projects.
    """
    base_query = select(Project)
    count_query = select(func.count(Project.id))

    # Apply filters
    if status:
        base_query = base_query.where(Project.status == status)
        count_query = count_query.where(Project.status == status)
    else:
        # Default: exclude deleted projects
        base_query = base_query.where(Project.status != "deleted")
        count_query = count_query.where(Project.status != "deleted")

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(Project.name.ilike(search_filter))
        count_query = count_query.where(Project.name.ilike(search_filter))

    # Get total count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Aggregate per-project stats in one query so we can sort the page on
    # them server-side without N+1 round trips.
    stats_subq = (
        select(
            Task.project_id.label("pid"),
            func.count(Task.id).label("task_count"),
            func.coalesce(
                func.sum(case((Task.status == "done", 1), else_=0)), 0
            ).label("done_count"),
            func.count(func.distinct(Task.source_transcript_id)).label("transcript_count"),
            func.max(Task.created_at).label("last_activity_at"),
        )
        .group_by(Task.project_id)
        .subquery()
    )

    base_query = (
        base_query.outerjoin(stats_subq, stats_subq.c.pid == Project.id)
        .add_columns(
            func.coalesce(stats_subq.c.task_count, 0),
            func.coalesce(stats_subq.c.done_count, 0),
            func.coalesce(stats_subq.c.transcript_count, 0),
            stats_subq.c.last_activity_at,
        )
    )

    sort_map = {
        "name": Project.name,
        "task_count": func.coalesce(stats_subq.c.task_count, 0),
        "last_activity_at": stats_subq.c.last_activity_at,
        "created_at": Project.created_at,
    }
    sort_col = sort_map.get(sort, stats_subq.c.last_activity_at)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    # Push NULL last_activity_at to the bottom regardless of direction so
    # never-active projects don't dominate the first page.
    base_query = base_query.order_by(
        direction.nulls_last() if hasattr(direction, "nulls_last") else direction,
        Project.created_at.desc(),
    ).offset(skip).limit(limit)

    rows = (await db.execute(base_query)).all()

    items = []
    for project, task_count, done_count, transcript_count, last_activity_at in rows:
        resp = ProjectResponse.model_validate(project)
        resp.task_count = int(task_count)
        resp.completed_task_count = int(done_count)
        resp.transcript_count = int(transcript_count)
        resp.last_activity_at = last_activity_at
        items.append(resp)

    page = skip // limit + 1 if limit > 0 else 1
    return {
        "total": total,
        "page": page,
        "page_size": limit,
        "items": items,
    }


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a project with tasks, transcripts, artifacts, and computed stats.

    Args:
        project_id: UUID of the project.
        db: Async database session.

    Returns:
        Project detail dict with nested tasks, artifacts, and stats.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    result = await db.execute(
        select(Project)
        .options(
            selectinload(Project.tasks),
            selectinload(Project.artifacts),
        )
        .where(Project.id == project_uuid)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Compute stats
    total_tasks = len(project.tasks) if project.tasks else 0
    tasks_done = sum(1 for t in project.tasks if t.status == "done") if project.tasks else 0
    tasks_todo = sum(1 for t in project.tasks if t.status == "todo") if project.tasks else 0
    total_artifacts = len(project.artifacts) if project.artifacts else 0

    stats = ProjectStats(
        total_tasks=total_tasks,
        tasks_done=tasks_done,
        tasks_todo=tasks_todo,
        total_artifacts=total_artifacts,
    )

    # Build task summaries
    task_summaries = [
        TaskSummary(id=t.id, title=t.title, status=t.status, priority=t.priority)
        for t in (project.tasks or [])
    ]

    # Build artifact summaries
    artifact_summaries = [
        ArtifactSummary(id=a.id, artifact_type=a.artifact_type, name=a.name)
        for a in (project.artifacts or [])
    ]

    # Distinct transcripts that contributed to this project. Tasks +
    # artifacts both carry source_transcript_id; union them via DISTINCT.
    transcript_count = (
        await db.execute(
            select(func.count(func.distinct(Task.source_transcript_id))).where(
                Task.project_id == project_uuid,
                Task.source_transcript_id.isnot(None),
            )
        )
    ).scalar_one() or 0

    # Last activity = newest task created_at (artifacts are coincident
    # with their tasks today).
    last_activity_at = (
        await db.execute(
            select(func.max(Task.created_at)).where(Task.project_id == project_uuid)
        )
    ).scalar_one_or_none()

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "metadata": project.metadata_,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "tasks": task_summaries,
        "artifacts": artifact_summaries,
        "stats": stats,
        # Flat fields the frontend ProjectDetail page reads directly.
        "task_count": total_tasks,
        "completed_task_count": tasks_done,
        "transcript_count": transcript_count,
        "last_activity_at": last_activity_at,
    }


@router.put("/{project_id}/status", response_model=ProjectResponse)
async def update_project_status(
    project_id: str,
    new_status: str = Query(..., description="New status value (active, archived, deleted)"),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Update a project's status.

    Args:
        project_id: UUID of the project.
        new_status: New status value.
        db: Async database session.

    Returns:
        Updated project.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID or status.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    if new_status not in ("active", "archived", "deleted"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status: {new_status}. Must be one of: active, archived, deleted",
        )

    result = await db.execute(select(Project).where(Project.id == project_uuid))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    project.status = new_status
    await db.commit()
    await db.refresh(project)

    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a project (soft delete — sets status to deleted).

    Args:
        project_id: UUID of the project.
        db: Async database session.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    result = await db.execute(select(Project).where(Project.id == project_uuid))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    await db.delete(project)
    await db.commit()
