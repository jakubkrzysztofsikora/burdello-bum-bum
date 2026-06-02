"""Tests for the Todoist API router.

Covers project/task export, sync status, and project listing.
Uses mocks for the TodoistClient to avoid external API calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Project, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_project(db: AsyncSession, name: str = "Export Project") -> Project:
    """Create a project for export tests."""
    project = Project(name=name, status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task(
    db: AsyncSession,
    project: Project,
    title: str = "Export Task",
    status: str = "todo",
    priority: str = "medium",
) -> Task:
    """Create a task for export tests."""
    task = Task(
        project_id=project.id,
        title=title,
        status=status,
        priority=priority,
        description="Task for export testing",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Get Todoist Projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_get_todoist_projects(mock_get_client, client: AsyncClient) -> None:
    """Listing Todoist projects returns projects from the API."""
    mock_client = AsyncMock()
    mock_client.get_projects.return_value = [
        {"id": "12345", "name": "Inbox"},
        {"id": "67890", "name": "Work"},
    ]
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/projects")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Inbox"
    assert data[1]["name"] == "Work"


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_get_todoist_projects_api_error(mock_get_client, client: AsyncClient) -> None:
    """Todoist API error returns 500."""
    mock_client = AsyncMock()
    mock_client.get_projects.side_effect = Exception("Connection timeout")
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/projects")
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Export Project
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_export_project(mock_get_client, client: AsyncClient, db_session: AsyncSession) -> None:
    """Exporting a project creates Todoist project and tasks."""
    mock_client = AsyncMock()
    mock_client.create_project.return_value = {"id": "td_proj_123", "name": "Export Project"}
    mock_client.create_task.return_value = {"id": "td_task_456", "content": "Export Task"}
    mock_get_client.return_value = mock_client

    project = await _create_project(db_session, name="Export Project")
    await _create_task(db_session, project, title="Task 1")
    await _create_task(db_session, project, title="Task 2", status="done")  # should be skipped

    response = await client.post(f"/api/v1/todoist/export/project/{project.id}?create_new=true")
    assert response.status_code == 200

    data = response.json()
    assert data["project_id"] == str(project.id)
    assert data["todoist_project_id"] == "td_proj_123"
    assert data["exported_tasks"] == 1  # Only the non-done task
    assert data["skipped_done"] == 1
    assert len(data["task_ids"]) == 1


@pytest.mark.asyncio
async def test_export_project_not_found(client: AsyncClient) -> None:
    """Exporting a non-existent project returns 404."""
    random_id = uuid.uuid4()
    response = await client.post(f"/api/v1/todoist/export/project/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_project_invalid_uuid(client: AsyncClient) -> None:
    """Exporting with invalid UUID returns 422."""
    response = await client.post("/api/v1/todoist/export/project/bad-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Export Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_export_task(mock_get_client, client: AsyncClient, db_session: AsyncSession) -> None:
    """Exporting a single task creates a Todoist task."""
    mock_client = AsyncMock()
    mock_client.create_task.return_value = {"id": "td_task_789", "content": "My Task"}
    mock_get_client.return_value = mock_client

    project = await _create_project(db_session)
    task = await _create_task(db_session, project, title="My Task")

    response = await client.post(f"/api/v1/todoist/export/task/{task.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["task_id"] == str(task.id)
    assert data["exported"] is True
    assert data["todoist_task"]["id"] == "td_task_789"


@pytest.mark.asyncio
async def test_export_task_not_found(client: AsyncClient) -> None:
    """Exporting a non-existent task returns 404."""
    random_id = uuid.uuid4()
    response = await client.post(f"/api/v1/todoist/export/task/{random_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Sync Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_sync_status_connected(mock_get_client, client: AsyncClient) -> None:
    """Sync status returns connected when API call succeeds."""
    mock_client = AsyncMock()
    mock_client.get_projects.return_value = [{"id": "1", "name": "Inbox"}]
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/sync-status")
    assert response.status_code == 200

    data = response.json()
    assert data["connected"] is True


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_sync_status_disconnected(mock_get_client, client: AsyncClient) -> None:
    """Sync status returns disconnected when API call fails."""
    mock_client = AsyncMock()
    mock_client.get_projects.side_effect = Exception("Auth failed")
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/sync-status")
    assert response.status_code == 200

    data = response.json()
    assert data["connected"] is False
    assert data["error"] is not None
