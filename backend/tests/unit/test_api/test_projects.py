"""Tests for the Projects API router.

Covers list, detail, status update, and delete operations.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Artifact, Project, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_project(
    db: AsyncSession,
    name: str = "Test Project",
    status: str = "active",
    **kwargs,
) -> Project:
    """Create a project in the database."""
    project = Project(
        name=name,
        description=kwargs.get("description", "A test project"),
        status=status,
        metadata_=kwargs.get("metadata", {}),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task(
    db: AsyncSession,
    project: Project,
    title: str = "Test Task",
    status: str = "todo",
    priority: str = "medium",
) -> Task:
    """Create a task associated with a project."""
    task = Task(
        project_id=project.id,
        title=title,
        status=status,
        priority=priority,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _create_artifact(
    db: AsyncSession,
    project: Project,
    name: str = "Test Artifact",
    artifact_type: str = "summary",
) -> Artifact:
    """Create an artifact associated with a project."""
    artifact = Artifact(
        project_id=project.id,
        name=name,
        artifact_type=artifact_type,
        content={"data": "test"},
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact


# ---------------------------------------------------------------------------
# List Projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects_empty(client: AsyncClient) -> None:
    """Listing projects when none exist returns empty items."""
    response = await client.get("/api/v1/projects/")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_projects_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """Listing projects returns paginated results."""
    for i in range(3):
        await _create_project(db_session, name=f"Project {i}")

    response = await client.get("/api/v1/projects/?limit=2")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_projects_filter_by_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """Filtering by status returns only matching projects."""
    await _create_project(db_session, name="Active", status="active")
    await _create_project(db_session, name="Archived", status="archived")

    response = await client.get("/api/v1/projects/?status=archived")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Archived"


@pytest.mark.asyncio
async def test_list_projects_excludes_deleted(client: AsyncClient, db_session: AsyncSession) -> None:
    """By default, deleted projects are excluded from listing."""
    await _create_project(db_session, name="Active", status="active")
    await _create_project(db_session, name="Deleted", status="deleted")

    response = await client.get("/api/v1/projects/")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Active"


@pytest.mark.asyncio
async def test_list_projects_search(client: AsyncClient, db_session: AsyncSession) -> None:
    """Search parameter filters projects by name."""
    await _create_project(db_session, name="Python Project")
    await _create_project(db_session, name="JavaScript Project")

    response = await client.get("/api/v1/projects/?search=Python")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert "Python" in data["items"][0]["name"]


# ---------------------------------------------------------------------------
# Get Project Detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_project_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Retrieving a project returns it with tasks, artifacts, and stats."""
    project = await _create_project(db_session, name="My Project")
    await _create_task(db_session, project, title="Task 1", status="todo")
    await _create_task(db_session, project, title="Task 2", status="done")
    await _create_artifact(db_session, project, name="Summary")

    response = await client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == str(project.id)
    assert data["name"] == "My Project"
    assert "tasks" in data
    assert "artifacts" in data
    assert "stats" in data
    assert data["stats"]["total_tasks"] == 2
    assert data["stats"]["tasks_done"] == 1
    assert data["stats"]["total_artifacts"] == 1


@pytest.mark.asyncio
async def test_get_project_not_found(client: AsyncClient) -> None:
    """Retrieving a non-existent project returns 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/projects/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_project_invalid_uuid(client: AsyncClient) -> None:
    """Retrieving with an invalid UUID returns 422."""
    response = await client.get("/api/v1/projects/bad-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Update Project Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_project_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """Updating a project's status returns the updated project."""
    project = await _create_project(db_session, name="To Archive", status="active")

    response = await client.put(f"/api/v1/projects/{project.id}/status?new_status=archived")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "archived"


@pytest.mark.asyncio
async def test_update_project_status_invalid(client: AsyncClient, db_session: AsyncSession) -> None:
    """Updating with an invalid status returns 422."""
    project = await _create_project(db_session, name="Test")

    response = await client.put(f"/api/v1/projects/{project.id}/status?new_status=invalid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_project_status_not_found(client: AsyncClient) -> None:
    """Updating a non-existent project returns 404."""
    random_id = uuid.uuid4()
    response = await client.put(f"/api/v1/projects/{random_id}/status?new_status=archived")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete Project
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_project(client: AsyncClient, db_session: AsyncSession) -> None:
    """Deleting a project returns 204."""
    project = await _create_project(db_session, name="To Delete")

    response = await client.delete(f"/api/v1/projects/{project.id}")
    assert response.status_code == 204

    response = await client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 404
