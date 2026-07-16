"""Tests for the Stats API router, including the weekly summary."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Artifact, Project, Task


async def _create_project(
    db: AsyncSession,
    name: str = "Test Project",
) -> Project:
    project = Project(name=name, status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task(
    db: AsyncSession,
    project: Project,
    title: str,
    status: str,
    updated_at: datetime | None = None,
) -> Task:
    task = Task(
        project_id=project.id,
        title=title,
        status=status,
        priority="medium",
    )
    if updated_at is not None:
        task.updated_at = updated_at
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _create_artifact(
    db: AsyncSession,
    project: Project,
    name: str,
    artifact_type: str = "document",
    created_at: datetime | None = None,
) -> Artifact:
    artifact = Artifact(
        project_id=project.id,
        name=name,
        artifact_type=artifact_type,
        content={},
    )
    if created_at is not None:
        artifact.created_at = created_at
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact


@pytest.mark.asyncio
async def test_weekly_summary_buckets(client: AsyncClient, db_session: AsyncSession) -> None:
    """The weekly summary groups tasks into done, in_progress, and stale."""
    project = await _create_project(db_session, "Weekly Summary Project")
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    old = now - timedelta(days=10)

    done_recent = await _create_task(db_session, project, "Done now", "done", now)
    in_progress_recent = await _create_task(
        db_session, project, "In progress now", "in_progress", now
    )
    stale_todo = await _create_task(db_session, project, "Stale todo", "todo", old)
    stale_in_progress = await _create_task(
        db_session, project, "Stale in progress", "in_progress", old
    )
    done_old = await _create_task(db_session, project, "Done old", "done", old)
    recent_artifact = await _create_artifact(
        db_session, project, "Recent doc", "document", now
    )

    response = await client.get("/api/v1/stats/weekly-summary")
    assert response.status_code == 200

    data = response.json()
    assert "since" in data
    assert data["done"]["count"] == 3  # 2 tasks + 1 artifact
    assert data["in_progress"]["count"] == 1
    assert data["stale"]["count"] == 2

    done_ids = {item["id"] for item in data["done"]["items"]}
    assert str(done_recent.id) in done_ids
    assert str(recent_artifact.id) in done_ids
    assert str(done_old.id) not in done_ids

    in_progress_ids = {item["id"] for item in data["in_progress"]["items"]}
    assert str(in_progress_recent.id) in in_progress_ids

    stale_ids = {item["id"] for item in data["stale"]["items"]}
    assert str(stale_todo.id) in stale_ids
    assert str(stale_in_progress.id) in stale_ids
    assert str(done_recent.id) not in stale_ids


@pytest.mark.asyncio
async def test_weekly_summary_empty(client: AsyncClient) -> None:
    """The weekly summary returns empty buckets when there is no activity."""
    response = await client.get("/api/v1/stats/weekly-summary")
    assert response.status_code == 200

    data = response.json()
    assert data["done"]["count"] == 0
    assert data["in_progress"]["count"] == 0
    assert data["stale"]["count"] == 0
    assert data["done"]["items"] == []
