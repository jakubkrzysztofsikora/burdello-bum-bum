"""Tests for the Search API router.

Covers search endpoint, similar transcripts, autocomplete, and facets.
Uses mocks for the HybridSearchEngine to avoid Qdrant dependencies.
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


async def _create_project(db: AsyncSession, name: str = "Searchable Project") -> Project:
    """Create a project for autocomplete tests."""
    project = Project(name=name, status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task(db: AsyncSession, title: str = "Searchable Task") -> Task:
    """Create a task for autocomplete tests."""
    task = Task(title=title, status="todo", priority="medium")
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Search Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.search._get_search_engine")
async def test_search(mock_get_engine, client: AsyncClient) -> None:
    """Search endpoint returns results from the search engine."""
    mock_engine = AsyncMock()
    mock_engine.search.return_value = [
        {
            "chunk_id": str(uuid.uuid4()),
            "transcript_id": str(uuid.uuid4()),
            "text": "Test result",
            "score": 0.95,
            "metadata": {},
        }
    ]
    mock_get_engine.return_value = mock_engine

    response = await client.post(
        "/api/v1/search/",
        json={"query": "test query", "limit": 10},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["query"] == "test query"
    assert data["total"] == 1
    assert len(data["results"]) == 1


@pytest.mark.asyncio
@patch("backend.api.routers.search._get_search_engine")
async def test_search_with_filters(mock_get_engine, client: AsyncClient) -> None:
    """Search with filters passes filters to the engine."""
    mock_engine = AsyncMock()
    mock_engine.search.return_value = []
    mock_get_engine.return_value = mock_engine

    response = await client.post(
        "/api/v1/search/",
        json={
            "query": "filtered query",
            "filters": {"source_type": "youtube"},
            "limit": 5,
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["query"] == "filtered query"
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_search_invalid_request(client: AsyncClient) -> None:
    """Search with invalid request body returns 422."""
    response = await client.post("/api/v1/search/", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
@patch("backend.api.routers.search._get_search_engine")
async def test_search_engine_error(mock_get_engine, client: AsyncClient) -> None:
    """Search engine error returns 500."""
    mock_engine = AsyncMock()
    mock_engine.search.side_effect = Exception("Qdrant connection failed")
    mock_get_engine.return_value = mock_engine

    response = await client.post(
        "/api/v1/search/",
        json={"query": "error test"},
    )
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Find Similar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.search._get_search_engine")
async def test_find_similar(mock_get_engine, client: AsyncClient) -> None:
    """Find similar endpoint returns similar transcripts."""
    mock_engine = AsyncMock()
    mock_engine.find_similar.return_value = [
        {
            "chunk_id": str(uuid.uuid4()),
            "transcript_id": str(uuid.uuid4()),
            "text": "Similar transcript",
            "score": 0.88,
            "metadata": {},
        }
    ]
    mock_get_engine.return_value = mock_engine

    transcript_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/search/similar/{transcript_id}?limit=5")
    assert response.status_code == 200

    data = response.json()
    assert data["transcript_id"] == transcript_id
    assert len(data["results"]) == 1


@pytest.mark.asyncio
async def test_find_similar_invalid_uuid(client: AsyncClient) -> None:
    """Find similar with invalid UUID returns 422."""
    response = await client.get("/api/v1/search/similar/invalid-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Autocomplete / Suggest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autocomplete(client: AsyncClient, db_session: AsyncSession) -> None:
    """Autocomplete returns matching projects and tasks."""
    await _create_project(db_session, name="Python Project")
    await _create_task(db_session, title="Python Task")

    response = await client.get("/api/v1/search/suggest?q=Python")
    assert response.status_code == 200

    data = response.json()
    assert len(data["projects"]) == 1
    assert len(data["tasks"]) == 1
    assert data["projects"][0]["name"] == "Python Project"
    assert data["tasks"][0]["title"] == "Python Task"


@pytest.mark.asyncio
async def test_autocomplete_no_matches(client: AsyncClient) -> None:
    """Autocomplete with no matches returns empty lists."""
    response = await client.get("/api/v1/search/suggest?q=xyznonexistent")
    assert response.status_code == 200

    data = response.json()
    assert data["projects"] == []
    assert data["tasks"] == []


@pytest.mark.asyncio
async def test_autocomplete_short_query(client: AsyncClient) -> None:
    """Autocomplete with too-short query returns 422."""
    response = await client.get("/api/v1/search/suggest?q=x")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_facets(client: AsyncClient, db_session: AsyncSession) -> None:
    """Facets endpoint returns counts grouped by status and provider."""
    response = await client.get("/api/v1/search/facets")
    assert response.status_code == 200

    data = response.json()
    assert "by_status" in data
    assert "by_provider" in data
    assert "by_project" in data
