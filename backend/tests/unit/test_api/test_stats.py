"""Tests for the Stats API router, including the weekly summary."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Artifact, Project, Task, Transcript


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
) -> Artifact:
    artifact = Artifact(
        project_id=project.id,
        name=name,
        artifact_type=artifact_type,
        content={"significance": "test artifact"},
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact


async def _create_transcript(
    db: AsyncSession,
    title: str = "Test Transcript",
) -> Transcript:
    transcript = Transcript(
        source_id=None,  # type: ignore[arg-type]
        title=title,
        status="completed",
    )
    db.add(transcript)
    await db.commit()
    await db.refresh(transcript)
    return transcript


@pytest.mark.asyncio
async def test_weekly_summary_returns_llm_summary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The weekly summary endpoint returns an LLM-generated summary string."""
    project = await _create_project(db_session, "Weekly Summary Project")
    now = datetime.utcnow()
    old = now - timedelta(days=10)

    await _create_task(db_session, project, "Done now", "done", now)
    await _create_task(db_session, project, "In progress now", "in_progress", now)
    await _create_task(db_session, project, "Stale todo", "todo", old)
    await _create_artifact(db_session, project, "Recent doc", "document")
    await _create_transcript(db_session, "Recent session")

    with patch("backend.api.routers.stats.MiningEngine") as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.generate_weekly_summary = AsyncMock(return_value="Test summary text.")

        response = await client.get("/api/v1/stats/weekly-summary")

    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert data["summary"] == "Test summary text."
    mock_engine.generate_weekly_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_weekly_summary_empty_when_no_activity(client: AsyncClient) -> None:
    """The weekly summary still calls the LLM even when there is no activity."""
    with patch("backend.api.routers.stats.MiningEngine") as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.generate_weekly_summary = AsyncMock(
            return_value="Nothing happened this week."
        )

        response = await client.get("/api/v1/stats/weekly-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "Nothing happened this week."
