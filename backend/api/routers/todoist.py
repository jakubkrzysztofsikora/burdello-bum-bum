"""API router for Todoist integration endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.models import Task, TodoistSyncRun
from backend.core.schemas import (
    TodoistSyncPlanResponse,
    TodoistSyncRunDetail,
    TodoistSyncRunListResponse,
)
from backend.integrations.todoist import TodoistClient
from backend.integrations.todoist_sync import TodoistSyncService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/todoist", tags=["todoist"])


def _get_todoist_client() -> TodoistClient:
    """Create a TodoistClient from application settings."""
    settings = get_settings()
    token = getattr(settings, "TODOIST_API_TOKEN", "") or ""
    if not token:
        token = "dummy-token"
    return TodoistClient(access_token=token)


def _get_sync_service(db: AsyncSession) -> TodoistSyncService:
    return TodoistSyncService(db=db, todoist_client=_get_todoist_client())


@router.get("/projects")
async def get_todoist_projects() -> list[dict[str, Any]]:
    """List projects from the connected Todoist account."""
    client = _get_todoist_client()
    try:
        return await client.get_projects()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Todoist API error: {exc!s}",
        )
    finally:
        await client.close()


@router.post("/sync/project/{project_id}/plan", response_model=TodoistSyncPlanResponse)
async def preview_project_sync(
    project_id: str,
    include_done: bool = Query(False, description="Include tasks already marked done"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Preview how a Burdello project would be synced to Todoist."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    service = _get_sync_service(db)
    try:
        return await service.build_plan(project_uuid, include_done=include_done)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    finally:
        await service.close()


@router.post("/sync/project/{project_id}")
async def sync_project(
    project_id: str,
    include_done: bool = Query(False, description="Include tasks already marked done"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run the Todoist sync pipeline for a Burdello project."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    service = _get_sync_service(db)
    try:
        return await service.run_sync(project_uuid, include_done=include_done)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    finally:
        await service.close()


@router.get("/sync/project/{project_id}/runs", response_model=TodoistSyncRunListResponse)
async def list_sync_runs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List Todoist sync history for a Burdello project."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {project_id}",
        )

    service = _get_sync_service(db)
    try:
        return await service.list_runs(project_uuid)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    finally:
        await service.close()


@router.get("/sync/runs/{run_id}", response_model=TodoistSyncRunDetail)
async def get_sync_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a single Todoist sync run."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {run_id}",
        )

    service = _get_sync_service(db)
    try:
        run = await service.get_run(run_uuid)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sync run {run_id} not found",
            )
        return run
    finally:
        await service.close()


@router.post("/export/project/{project_id}")
async def export_project_compat(
    project_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    include_done: bool = Query(False, description="Include tasks already marked done"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Compatibility wrapper for the old project export endpoint."""
    if payload and "include_done" in payload:
        include_done = bool(payload["include_done"])
    return await sync_project(project_id, include_done=include_done, db=db)


@router.post("/export/task/{task_id}")
async def export_task(
    task_id: str,
    todoist_project_id: str | None = Query(None, description="Target Todoist project ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export a single task to Todoist.

    This remains as a compatibility path and now respects an explicit target
    Todoist project when provided.
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
    finally:
        await client.close()

    return {
        "task_id": task_id,
        "todoist_task": td_task,
        "exported": True,
    }


@router.get("/sync-status")
async def get_sync_status() -> dict[str, Any]:
    """Check the Todoist integration sync status."""
    settings = get_settings()
    token = getattr(settings, "TODOIST_API_TOKEN", "") or ""

    client = _get_todoist_client()
    connected = False
    error = None
    try:
        await client.get_projects()
        connected = True
    except Exception as exc:
        error = str(exc)
    finally:
        await client.close()

    return {
        "connected": connected,
        "has_token": bool(token) and token != "dummy-token",
        "error": error,
    }


def _priority_to_todoist(priority: str | None) -> int:
    """Convert BB priority to Todoist priority (1-4, where 4 is highest)."""
    mapping = {"low": 1, "medium": 2, "high": 4}
    return mapping.get(priority or "medium", 2)
