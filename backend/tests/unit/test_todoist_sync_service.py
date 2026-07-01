"""Tests for the Todoist sync service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Project, Task, TodoistSyncRun, TodoistTaskLink
from backend.integrations.todoist_sync import TodoistSyncService


async def _create_project(db: AsyncSession, name: str = "Sync Project") -> Project:
    project = Project(name=name, status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task(
    db: AsyncSession,
    project: Project,
    title: str,
    description: str = "",
    status: str = "todo",
) -> Task:
    task = Task(
        project_id=project.id,
        title=title,
        description=description,
        status=status,
        priority="medium",
        tags=["backend"],
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_build_plan_matches_existing_todoist_project(db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Auth Sync")
    task = await _create_task(db_session, project, "Build auth flow", "Add JWT login")

    todoist_client = AsyncMock()
    todoist_client.get_projects.return_value = [
        {"id": "todoist_work", "name": "Work"},
        {"id": "todoist_inbox", "name": "Inbox"},
    ]

    llm_client = AsyncMock()
    llm_client.extract_json.return_value = {
        "epics": [
            {
                "key": "work",
                "name": "Work",
                "summary": "Auth work",
                "task_ids": [str(task.id)],
            }
        ]
    }

    service = TodoistSyncService(db=db_session, todoist_client=todoist_client, llm_client=llm_client)
    plan = await service.build_plan(project.id)
    await service.close()

    assert plan["project_name"] == "Auth Sync"
    assert plan["epics"][0]["match"]["todoist_project_name"] == "Work"
    assert plan["epics"][0]["task_count"] == 1


@pytest.mark.asyncio
async def test_build_plan_degrades_when_todoist_projects_unavailable(db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Offline Preview")
    await _create_task(db_session, project, "Write docs", "Add usage notes")

    todoist_client = AsyncMock()
    todoist_client.get_projects.side_effect = Exception("Auth failed")

    llm_client = AsyncMock()
    llm_client.extract_json.return_value = {"epics": []}

    service = TodoistSyncService(db=db_session, todoist_client=todoist_client, llm_client=llm_client)
    plan = await service.build_plan(project.id)
    await service.close()

    assert plan["todoist_projects"] == []
    assert plan["todoist_projects_error"] == "Auth failed"
    assert plan["epics"][0]["match"]["source"] == "unmatched" or plan["epics"][0]["match"]["source"] == "inbox"


@pytest.mark.asyncio
async def test_run_sync_creates_links_and_run_rows(db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Sync Project")
    task = await _create_task(db_session, project, "Write docs", "Update README")

    todoist_client = AsyncMock()
    todoist_client.get_projects.return_value = [
        {"id": "todoist_docs", "name": "Docs"},
        {"id": "todoist_inbox", "name": "Inbox"},
    ]
    todoist_client.create_task.return_value = {"id": "td_1", "content": task.title}
    todoist_client.update_task.return_value = {"id": "td_1", "content": task.title}

    llm_client = AsyncMock()
    llm_client.extract_json.return_value = {
        "epics": [
            {
                "key": "docs",
                "name": "Docs",
                "summary": "Documentation updates",
                "task_ids": [str(task.id)],
            }
        ]
    }

    service = TodoistSyncService(db=db_session, todoist_client=todoist_client, llm_client=llm_client)
    result = await service.run_sync(project.id)
    await service.close()

    assert result["status"] == "completed"
    assert result["result_data"]["counts"]["created"] == 1

    link = (
        await db_session.execute(
            select(TodoistTaskLink).where(TodoistTaskLink.task_id == task.id)
        )
    ).scalar_one()
    assert link.todoist_task_id == "td_1"

    run = (
        await db_session.execute(select(TodoistSyncRun).where(TodoistSyncRun.project_id == project.id))
    ).scalar_one()
    assert run.status == "completed"
    assert run.result_data is not None


@pytest.mark.asyncio
async def test_run_sync_updates_existing_link(db_session: AsyncSession) -> None:
    project = await _create_project(db_session, name="Idempotent Project")
    task = await _create_task(db_session, project, "Ship feature", "Keep it working")

    todoist_client = AsyncMock()
    todoist_client.get_projects.return_value = [
        {"id": "todoist_work", "name": "Work"},
        {"id": "todoist_inbox", "name": "Inbox"},
    ]
    todoist_client.create_task.return_value = {"id": "td_1", "content": task.title}
    todoist_client.update_task.return_value = {"id": "td_1", "content": task.title}

    llm_client = AsyncMock()
    llm_client.extract_json.return_value = {
        "epics": [
            {
                "key": "work",
                "name": "Work",
                "summary": "General work",
                "task_ids": [str(task.id)],
            }
        ]
    }

    service = TodoistSyncService(db=db_session, todoist_client=todoist_client, llm_client=llm_client)
    await service.run_sync(project.id)
    todoist_client.create_task.reset_mock()
    todoist_client.update_task.reset_mock()

    await service.run_sync(project.id)
    await service.close()

    todoist_client.update_task.assert_awaited()
    todoist_client.create_task.assert_not_awaited()
