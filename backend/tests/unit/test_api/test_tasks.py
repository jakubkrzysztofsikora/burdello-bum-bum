"""Tests for the Tasks API router.

Covers list (with filters), kanban board, status update, and delete operations.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Project, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_project(db: AsyncSession, name: str = "Test Project") -> Project:
    """Create a project for task association."""
    project = Project(name=name, status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task(
    db: AsyncSession,
    project: Project | None = None,
    title: str = "Test Task",
    status: str = "todo",
    priority: str = "medium",
    **kwargs,
) -> Task:
    """Create a task in the database."""
    task = Task(
        project_id=project.id if project else None,
        title=title,
        status=status,
        priority=priority,
        description=kwargs.get("description", "A test task"),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# List Tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_empty(client: AsyncClient) -> None:
    """Listing tasks when none exist returns empty items."""
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_tasks_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """Listing tasks returns paginated results."""
    for i in range(3):
        await _create_task(db_session, title=f"Task {i}")

    response = await client.get("/api/v1/tasks/?limit=2")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """Filtering by status returns only matching tasks."""
    await _create_task(db_session, title="Todo Task", status="todo")
    await _create_task(db_session, title="Done Task", status="done")

    response = await client.get("/api/v1/tasks/?status=done")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Done Task"


@pytest.mark.asyncio
async def test_list_tasks_filter_by_priority(client: AsyncClient, db_session: AsyncSession) -> None:
    """Filtering by priority returns only matching tasks."""
    await _create_task(db_session, title="High Priority", priority="high")
    await _create_task(db_session, title="Low Priority", priority="low")

    response = await client.get("/api/v1/tasks/?priority=high")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["priority"] == "high"


@pytest.mark.asyncio
async def test_list_tasks_filter_by_project(client: AsyncClient, db_session: AsyncSession) -> None:
    """Filtering by project_id returns only associated tasks."""
    project = await _create_project(db_session, name="My Project")
    await _create_task(db_session, project=project, title="Project Task")
    await _create_task(db_session, title="Orphan Task")

    response = await client.get(f"/api/v1/tasks/?project_id={project.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Project Task"


@pytest.mark.asyncio
async def test_list_tasks_search(client: AsyncClient, db_session: AsyncSession) -> None:
    """Search parameter filters tasks by title."""
    await _create_task(db_session, title="Fix bug in parser")
    await _create_task(db_session, title="Write documentation")

    response = await client.get("/api/v1/tasks/?search=bug")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert "bug" in data["items"][0]["title"]


# ---------------------------------------------------------------------------
# Kanban Board
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_kanban_board(client: AsyncClient, db_session: AsyncSession) -> None:
    """Kanban board returns tasks organized by status columns."""
    await _create_task(db_session, title="Todo 1", status="todo")
    await _create_task(db_session, title="Todo 2", status="todo")
    await _create_task(db_session, title="In Progress", status="in_progress")
    await _create_task(db_session, title="Completed", status="done")
    await _create_task(db_session, title="Abandoned", status="cancelled")

    response = await client.get("/api/v1/tasks/kanban")
    assert response.status_code == 200

    data = response.json()
    assert "todo" in data
    assert "in_progress" in data
    assert "completed" in data
    assert "abandoned" in data
    assert len(data["todo"]) == 2
    assert len(data["in_progress"]) == 1
    assert len(data["completed"]) == 1
    assert len(data["abandoned"]) == 1


@pytest.mark.asyncio
async def test_get_kanban_empty(client: AsyncClient) -> None:
    """Kanban board returns empty columns when no tasks exist."""
    response = await client.get("/api/v1/tasks/kanban")
    assert response.status_code == 200

    data = response.json()
    assert data["todo"] == []
    assert data["in_progress"] == []
    assert data["completed"] == []
    assert data["abandoned"] == []


# ---------------------------------------------------------------------------
# Update Task Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """Updating a task's status returns the updated task."""
    task = await _create_task(db_session, title="To Update", status="todo")

    response = await client.put(f"/api/v1/tasks/{task.id}/status?new_status=in_progress")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_update_task_status_invalid(client: AsyncClient, db_session: AsyncSession) -> None:
    """Updating with an invalid status returns 422."""
    task = await _create_task(db_session, title="Test")

    response = await client.put(f"/api/v1/tasks/{task.id}/status?new_status=invalid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_task_status_not_found(client: AsyncClient) -> None:
    """Updating a non-existent task returns 404."""
    random_id = uuid.uuid4()
    response = await client.put(f"/api/v1/tasks/{random_id}/status?new_status=done")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Get Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Retrieving an existing task returns it."""
    task = await _create_task(db_session, title="My Task", priority="high")

    response = await client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == str(task.id)
    assert data["title"] == "My Task"
    assert data["priority"] == "high"


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient) -> None:
    """Retrieving a non-existent task returns 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/tasks/{random_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient, db_session: AsyncSession) -> None:
    """Deleting a task returns 204."""
    task = await _create_task(db_session, title="To Delete")

    response = await client.delete(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 204

    response = await client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 404
