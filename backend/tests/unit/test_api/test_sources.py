"""Tests for the Sources API router.

Covers list, retrieve, and delete operations for transcript sources.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Source


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _create_source(
    db: AsyncSession,
    source_type: str = "youtube",
    title: str = "Test Source",
    **kwargs,
) -> Source:
    """Helper to create a source in the database."""
    source = Source(
        source_type=source_type,
        title=title,
        description=kwargs.get("description", "A test source"),
        url=kwargs.get("url", "https://example.com"),
        language=kwargs.get("language", "en"),
        duration_seconds=kwargs.get("duration_seconds", 3600),
        metadata_=kwargs.get("metadata", {"key": "value"}),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


# ---------------------------------------------------------------------------
# List Sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_empty(client: AsyncClient) -> None:
    """Listing sources when none exist returns an empty list."""
    response = await client.get("/api/v1/sources/")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_sources_pagination(client: AsyncClient, db_session: AsyncSession) -> None:
    """Listing sources respects skip/limit pagination."""
    for i in range(5):
        await _create_source(db_session, title=f"Source {i}")

    response = await client.get("/api/v1/sources/?skip=0&limit=2")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2

    # Second page
    response = await client.get("/api/v1/sources/?skip=2&limit=2")
    data = response.json()
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_sources_filter_by_type(client: AsyncClient, db_session: AsyncSession) -> None:
    """Filtering by source_type returns only matching sources."""
    await _create_source(db_session, source_type="youtube", title="YouTube Video")
    await _create_source(db_session, source_type="audio_file", title="Audio File")

    response = await client.get("/api/v1/sources/?source_type=youtube")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["source_type"] == "youtube"


@pytest.mark.asyncio
async def test_list_sources_search(client: AsyncClient, db_session: AsyncSession) -> None:
    """Search parameter filters sources by title/description."""
    await _create_source(db_session, title="Python Tutorial")
    await _create_source(db_session, title="JavaScript Guide")

    response = await client.get("/api/v1/sources/?search=Python")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert "Python" in data["items"][0]["title"]


# ---------------------------------------------------------------------------
# Get Source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_source_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Retrieving an existing source by ID returns the source."""
    source = await _create_source(db_session, title="My Source")

    response = await client.get(f"/api/v1/sources/{source.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == str(source.id)
    assert data["title"] == "My Source"
    assert data["source_type"] == "youtube"


@pytest.mark.asyncio
async def test_get_source_not_found(client: AsyncClient) -> None:
    """Retrieving a non-existent source returns 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/sources/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_source_invalid_uuid(client: AsyncClient) -> None:
    """Retrieving with an invalid UUID returns 422."""
    response = await client.get("/api/v1/sources/not-a-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Delete Source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_source_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Deleting an existing source returns 204."""
    source = await _create_source(db_session, title="To Delete")

    response = await client.delete(f"/api/v1/sources/{source.id}")
    assert response.status_code == 204

    # Verify it's gone
    response = await client.get(f"/api/v1/sources/{source.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_source_not_found(client: AsyncClient) -> None:
    """Deleting a non-existent source returns 404."""
    random_id = uuid.uuid4()
    response = await client.delete(f"/api/v1/sources/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_source_invalid_uuid(client: AsyncClient) -> None:
    """Deleting with an invalid UUID returns 422."""
    response = await client.delete("/api/v1/sources/bad-uuid")
    assert response.status_code == 422
