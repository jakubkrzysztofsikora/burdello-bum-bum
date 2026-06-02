"""API router for Todoist integration endpoints.

Provides project/task export to Todoist, sync status, and project
listing from the Todoist API.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.models import Project, Task
from backend.integrations.todoist import TodoistClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/todoist", tags=["todoist"])


def _get_todoist_client() -> TodoistClient:
    """Create a TodoistClient from application settings.

    Returns:
        Configured ``TodoistClient``.

    Raises:
        HTTPException: 500 if Todoist token is not configured.
    """
    settings = get_settings()
    token = getattr(settings, "TODOIST_API_TOKEN", "") or ""
    if not token:
        # Use a dummy token for development — the client will fail
        # on actual API calls but allows route testing
        token = "dummy-token"
    return TodoistClient(access_token=token)


@router.get("/projects")
async def get_todoist_projects() -> list[dict[str, Any]]:
    """List projects from the connected Todoist account.

    Returns:
        List of Todoist project dicts.

    Raises:
        HTTPException: 500 if Todoist API call fails.
    """
    client = _get_todoist_client()
    try:
        projects = await client.get_projects()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Todoist API error: {exc!s}",
        )
    return projects


@router.post("/export/project/{project_id}")
async def export_project(
    project_id: str,
    create_new: bool = Query(True, description="Create a new Todoist project"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export a BB project and its tasks to Todoist.

    Args:
        project_id: UUID of the Burdello Bum-Bum project.
        create_new: Whether to create a new Todoist project.
        db: Async database session.

    Returns:
        Dict with export summary and created item IDs.

    Raises:
        HTTPException: 404 if project not found, 500 if Todoist API fails.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    # Get project with tasks
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.id == project_uuid)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    client = _get_todoist_client()

    exported_task_ids: list[str] = []
    errors: list[str] = []

    try:
        if create_new:
            todoist_project = await client.create_project(name=project.name)
            todoist_project_id = todoist_project.get("id", "")
        else:
            todoist_project_id = ""
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Todoist project: {exc!s}",
        )

    # Export tasks
    for task in project.tasks or []:
        if task.status == "done":
            continue
        try:
            td_task = await client.create_task(
                project_id=todoist_project_id,
                content=task.title,
                description=task.description or "",
                priority=_priority_to_todoist(task.priority),
            )
            exported_task_ids.append(td_task.get("id", ""))
        except Exception as exc:
            errors.append(f"Task {task.id}: {exc!s}")

    return {
        "project_id": project_id,
        "todoist_project_id": todoist_project_id,
        "exported_tasks": len(exported_task_ids),
        "task_ids": exported_task_ids,
        "errors": errors,
        "skipped_done": sum(1 for t in (project.tasks or []) if t.status == "done"),
    }


@router.post("/export/task/{task_id}")
async def export_task(
    task_id: str,
    todoist_project_id: str | None = Query(None, description="Target Todoist project ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export a single task to Todoist.

    Args:
        task_id: UUID of the Burdello Bum-Bum task.
        todoist_project_id: Optional target Todoist project ID.
        db: Async database session.

    Returns:
        Dict with created Todoist task details.

    Raises:
        HTTPException: 404 if task not found, 500 if Todoist API fails.
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

    client = _get_todoist_client()

    try:
        td_task = await client.create_task(
            project_id=todoist_project_id or "",
            content=task.title,
            description=task.description or "",
            priority=_priority_to_todoist(task.priority),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Todoist API error: {exc!s}",
        )

    return {
        "task_id": task_id,
        "todoist_task": td_task,
        "exported": True,
    }


@router.get("/sync-status")
async def get_sync_status() -> dict[str, Any]:
    """Check the Todoist integration sync status.

    Returns:
        Dict with connection status and configuration info.
    """
    settings = get_settings()
    token = getattr(settings, "TODOIST_API_TOKEN", "") or ""

    client = _get_todoist_client()

    # Try a lightweight API call
    connected = False
    error = None
    try:
        await client.get_projects()
        connected = True
    except Exception as exc:
        error = str(exc)

    return {
        "connected": connected,
        "has_token": bool(token) and token != "dummy-token",
        "error": error,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _priority_to_todoist(priority: str | None) -> int:
    """Convert BB priority to Todoist priority (1-4, where 4 is highest).

    Args:
        priority: BB priority string (low, medium, high).

    Returns:
        Todoist priority integer (1-4).
    """
    mapping = {"low": 1, "medium": 2, "high": 4}
    return mapping.get(priority or "medium", 2)
