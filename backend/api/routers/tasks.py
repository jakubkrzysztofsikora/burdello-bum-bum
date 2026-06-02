"""API router for Task endpoints.

Provides list, kanban board, and status update operations for tasks
with filtering and pagination.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.models import Project, Task
from backend.core.schemas import TaskListResponse, TaskResponse, TaskSummary

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Valid task statuses
VALID_STATUSES = {"todo", "in_progress", "done", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high"}


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    project_id: str | None = Query(None, description="Filter by project ID"),
    status: str | None = Query(None, description="Filter by status (todo, in_progress, done, cancelled)"),
    priority: str | None = Query(None, description="Filter by priority (low, medium, high)"),
    search: str | None = Query(None, description="Search in title"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-created_at", description="Sort field, prefix with - for descending"),
) -> dict[str, Any]:
    """List tasks with filtering, sorting, and pagination.

    Args:
        db: Async database session.
        project_id: Optional project ID filter.
        status: Optional status filter.
        priority: Optional priority filter.
        search: Optional text search on task title.
        skip: Pagination offset.
        limit: Maximum items to return.
        sort: Sort field with optional ``-`` prefix for descending.

    Returns:
        Paginated list of tasks.
    """
    base_query = select(Task)
    count_query = select(func.count(Task.id))

    # Apply filters
    if status:
        base_query = base_query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)

    if priority:
        base_query = base_query.where(Task.priority == priority)
        count_query = count_query.where(Task.priority == priority)

    if project_id:
        try:
            project_uuid = uuid.UUID(project_id)
            base_query = base_query.where(Task.project_id == project_uuid)
            count_query = count_query.where(Task.project_id == project_uuid)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid project UUID: {project_id}",
            )

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(Task.title.ilike(search_filter))
        count_query = count_query.where(Task.title.ilike(search_filter))

    # Get total count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply sorting
    if sort.startswith("-"):
        sort_field = sort[1:]
        base_query = base_query.order_by(getattr(Task, sort_field, Task.created_at).desc())
    else:
        base_query = base_query.order_by(getattr(Task, sort, Task.created_at).asc())

    # Apply pagination
    base_query = base_query.offset(skip).limit(limit)

    result = await db.execute(base_query)
    items = list(result.scalars().all())

    page = skip // limit + 1 if limit > 0 else 1
    return {
        "total": total,
        "page": page,
        "page_size": limit,
        "items": items,
    }


@router.get("/kanban")
async def get_kanban_board(
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """Get tasks organized into Kanban columns.

    Args:
        db: Async database session.

    Returns:
        Dict with keys ``todo``, ``in_progress``, ``completed``, ``abandoned``
        containing lists of task summaries.
    """
    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    tasks = result.scalars().all()

    columns: dict[str, list[dict[str, Any]]] = {
        "todo": [],
        "in_progress": [],
        "completed": [],
        "abandoned": [],
    }

    for task in tasks:
        task_summary = {
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "description": task.description,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }

        if task.status == "todo":
            columns["todo"].append(task_summary)
        elif task.status == "in_progress":
            columns["in_progress"].append(task_summary)
        elif task.status == "done":
            columns["completed"].append(task_summary)
        elif task.status == "cancelled":
            columns["abandoned"].append(task_summary)

    return columns


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Get a single task by ID.

    Args:
        task_id: UUID of the task.
        db: Async database session.

    Returns:
        The task.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {task_id}",
        )

    result = await db.execute(select(Task).where(Task.id == task_uuid))
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    return task


@router.put("/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: str,
    new_status: str = Query(..., description="New status (todo, in_progress, done, cancelled)"),
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Update a task's status.

    Args:
        task_id: UUID of the task.
        new_status: New status value.
        db: Async database session.

    Returns:
        Updated task.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID or status.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {task_id}",
        )

    if new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status: {new_status}. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    result = await db.execute(select(Task).where(Task.id == task_uuid))
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    task.status = new_status
    await db.commit()
    await db.refresh(task)

    return task


@router.put("/{task_id}/priority", response_model=TaskResponse)
async def update_task_priority(
    task_id: str,
    new_priority: str = Query(..., description="New priority (low, medium, high)"),
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Update a task's priority.

    Args:
        task_id: UUID of the task.
        new_priority: New priority value.
        db: Async database session.

    Returns:
        Updated task.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID or priority.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {task_id}",
        )

    if new_priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid priority: {new_priority}. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}",
        )

    result = await db.execute(select(Task).where(Task.id == task_uuid))
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    task.priority = new_priority
    await db.commit()
    await db.refresh(task)

    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a task.

    Args:
        task_id: UUID of the task.
        db: Async database session.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {task_id}",
        )

    result = await db.execute(select(Task).where(Task.id == task_uuid))
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    await db.delete(task)
    await db.commit()
