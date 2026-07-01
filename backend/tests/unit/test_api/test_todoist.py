"""Tests for the Todoist API router."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Project, Task


async def _create_project(db: AsyncSession, name: str = "Export Project") -> Project:
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


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_get_todoist_projects(mock_get_client, client: AsyncClient) -> None:
    mock_client = AsyncMock()
    mock_client.get_projects.return_value = [
        {"id": "12345", "name": "Inbox"},
        {"id": "67890", "name": "Work"},
    ]
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/projects")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Inbox"
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_get_todoist_projects_api_error(mock_get_client, client: AsyncClient) -> None:
    mock_client = AsyncMock()
    mock_client.get_projects.side_effect = Exception("Connection timeout")
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/projects")
    assert response.status_code == 500
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_sync_service")
async def test_preview_project_sync(mock_get_service, client: AsyncClient, db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Preview Project")
    service = AsyncMock()
    service.build_plan.return_value = {
        "project_id": str(project.id),
        "project_name": project.name,
        "include_done": False,
        "todoist_inbox_project_id": "inbox_123",
        "todoist_projects_error": None,
        "todoist_projects": [{"id": "inbox_123", "name": "Inbox"}],
        "epics": [
            {
                "epic_key": "feature",
                "epic_name": "Feature",
                "summary": "Feature work",
                "task_count": 1,
                "task_ids": [str(uuid.uuid4())],
                "match": {
                    "todoist_project_id": "proj_1",
                    "todoist_project_name": "Work",
                    "score": 0.9,
                    "reason": "fuzzy name match",
                    "source": "fuzzy",
                },
            }
        ],
        "skipped_done": 0,
        "total_tasks": 1,
        "eligible_tasks": 1,
    }
    mock_get_service.return_value = service

    response = await client.post(f"/api/v1/todoist/sync/project/{project.id}/plan")
    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Preview Project"
    assert data["epics"][0]["match"]["todoist_project_name"] == "Work"
    service.build_plan.assert_awaited_once()
    service.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_sync_service")
async def test_run_project_sync(mock_get_service, client: AsyncClient, db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Run Project")
    service = AsyncMock()
    service.run_sync.return_value = {
        "id": uuid.uuid4(),
        "project_id": str(project.id),
        "project_name": project.name,
        "status": "completed",
        "include_done": False,
        "todoist_inbox_project_id": "inbox_123",
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": "2026-06-28T00:00:00Z",
        "error_text": None,
        "metrics": {"created": 1, "updated": 0, "skipped": 0},
        "plan_data": {},
        "result_data": {"counts": {"created": 1, "updated": 0, "skipped": 0}, "errors": [], "epics": []},
    }
    mock_get_service.return_value = service

    response = await client.post(f"/api/v1/todoist/sync/project/{project.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    service.run_sync.assert_awaited_once()
    service.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_sync_service")
async def test_list_sync_runs(mock_get_service, client: AsyncClient, db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="History Project")
    service = AsyncMock()
    service.list_runs.return_value = {
        "total": 1,
        "items": [
            {
                "id": uuid.uuid4(),
                "project_id": project.id,
                "project_name": project.name,
                "status": "completed",
                "include_done": False,
                "todoist_inbox_project_id": "inbox_123",
                "created_at": "2026-06-28T00:00:00Z",
                "updated_at": "2026-06-28T00:00:00Z",
                "error_text": None,
                "metrics": {"created": 1},
            }
        ],
    }
    mock_get_service.return_value = service

    response = await client.get(f"/api/v1/todoist/sync/project/{project.id}/runs")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    service.list_runs.assert_awaited_once()
    service.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_sync_service")
async def test_get_sync_run(mock_get_service, client: AsyncClient, db_session: AsyncSession) -> None:
    service = AsyncMock()
    run_id = uuid.uuid4()
    service.get_run.return_value = {
        "id": run_id,
        "project_id": uuid.uuid4(),
        "project_name": "Run Project",
        "status": "completed",
        "include_done": False,
        "todoist_inbox_project_id": "inbox_123",
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": "2026-06-28T00:00:00Z",
        "error_text": None,
        "metrics": {"created": 1},
        "plan_data": {},
        "result_data": {},
    }
    mock_get_service.return_value = service

    response = await client.get(f"/api/v1/todoist/sync/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(run_id)
    service.get_run.assert_awaited_once()
    service.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_sync_service")
async def test_export_project_compatibility(mock_get_service, client: AsyncClient, db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Compat Project")
    service = AsyncMock()
    service.run_sync.return_value = {
        "id": uuid.uuid4(),
        "project_id": str(project.id),
        "project_name": project.name,
        "status": "completed",
        "include_done": False,
        "todoist_inbox_project_id": "inbox_123",
        "created_at": "2026-06-28T00:00:00Z",
        "updated_at": "2026-06-28T00:00:00Z",
        "error_text": None,
        "metrics": {"created": 1},
        "plan_data": {},
        "result_data": {},
    }
    mock_get_service.return_value = service

    response = await client.post(f"/api/v1/todoist/export/project/{project.id}", json={"todoist_project_id": "ignored"})
    assert response.status_code == 200
    service.run_sync.assert_awaited_once()
    service.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_export_task(mock_get_client, client: AsyncClient, db_session: AsyncSession) -> None:
    mock_client = AsyncMock()
    mock_client.create_task.return_value = {"id": "td_task_789", "content": "My Task"}
    mock_get_client.return_value = mock_client

    project = await _create_project(db_session)
    task = await _create_task(db_session, project, title="My Task")

    response = await client.post(f"/api/v1/todoist/export/task/{task.id}")
    assert response.status_code == 200
    assert response.json()["todoist_task"]["id"] == "td_task_789"
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_task_not_found(client: AsyncClient) -> None:
    response = await client.post(f"/api/v1/todoist/export/task/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_sync_status_connected(mock_get_client, client: AsyncClient) -> None:
    mock_client = AsyncMock()
    mock_client.get_projects.return_value = [{"id": "1", "name": "Inbox"}]
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/sync-status")
    assert response.status_code == 200
    assert response.json()["connected"] is True
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.routers.todoist._get_todoist_client")
async def test_sync_status_disconnected(mock_get_client, client: AsyncClient) -> None:
    mock_client = AsyncMock()
    mock_client.get_projects.side_effect = Exception("Auth failed")
    mock_get_client.return_value = mock_client

    response = await client.get("/api/v1/todoist/sync-status")
    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["error"] is not None
    mock_client.close.assert_awaited_once()
