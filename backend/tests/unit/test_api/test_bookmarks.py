"""Tests for the Bookmarks API router.

Covers list, create, delete, and patch operations.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Bookmark, Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_project(db: AsyncSession, name: str = "BM Project") -> Project:
    """Create a project in the database."""
    project = Project(name=name, description="A test project", status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_bookmark(
    db: AsyncSession,
    project: Project | None = None,
    note_text: str = "revisit auth retry logic",
    pinned: bool = False,
    **kwargs,
) -> Bookmark:
    """Create a bookmark in the database."""
    bookmark = Bookmark(
        project_id=project.id if project else None,
        note_text=note_text,
        author=kwargs.get("author", "claude-code"),
        pinned=pinned,
        tags=kwargs.get("tags"),
        session_id=kwargs.get("session_id"),
    )
    db.add(bookmark)
    await db.commit()
    await db.refresh(bookmark)
    return bookmark


# ---------------------------------------------------------------------------
# List Bookmarks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bookmarks_empty(client: AsyncClient) -> None:
    """Listing bookmarks when none exist returns empty items."""
    response = await client.get("/api/v1/bookmarks/")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_bookmarks_with_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Listing returns {total, items} for the project's bookmarks."""
    project = await _create_project(db_session)
    await _create_bookmark(db_session, project, note_text="note one")
    await _create_bookmark(db_session, project, note_text="note two")

    response = await client.get(f"/api/v1/bookmarks/?project_id={project.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    notes = {item["note_text"] for item in data["items"]}
    assert notes == {"note one", "note two"}


@pytest.mark.asyncio
async def test_list_bookmarks_pinned_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pinned bookmarks sort ahead of unpinned ones."""
    project = await _create_project(db_session)
    await _create_bookmark(db_session, project, note_text="unpinned", pinned=False)
    await _create_bookmark(db_session, project, note_text="pinned", pinned=True)

    response = await client.get(f"/api/v1/bookmarks/?project_id={project.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["items"][0]["note_text"] == "pinned"


# ---------------------------------------------------------------------------
# Create Bookmark
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_bookmark_roundtrip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Creating a bookmark returns 201 and it appears in the list."""
    project = await _create_project(db_session)

    response = await client.post(
        "/api/v1/bookmarks/",
        json={
            "note_text": "come back and verify X",
            "project_id": str(project.id),
            "author": "claude-code",
        },
    )
    assert response.status_code == 201

    created = response.json()
    assert created["note_text"] == "come back and verify X"
    assert created["project_id"] == str(project.id)
    assert created["ingest_status"] == "none"

    list_resp = await client.get(f"/api/v1/bookmarks/?project_id={project.id}")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == created["id"]


# ---------------------------------------------------------------------------
# Delete Bookmark
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_bookmark(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting a bookmark returns 204; deleting again returns 404."""
    project = await _create_project(db_session)
    bookmark = await _create_bookmark(db_session, project)

    response = await client.delete(f"/api/v1/bookmarks/{bookmark.id}")
    assert response.status_code == 204

    again = await client.delete(f"/api/v1/bookmarks/{bookmark.id}")
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_delete_bookmark_not_found(client: AsyncClient) -> None:
    """Deleting a non-existent bookmark returns 404."""
    response = await client.delete(f"/api/v1/bookmarks/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Patch Bookmark
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_bookmark_updates_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Patching a bookmark updates the provided fields."""
    project = await _create_project(db_session)
    bookmark = await _create_bookmark(db_session, project, pinned=False)

    response = await client.patch(
        f"/api/v1/bookmarks/{bookmark.id}",
        json={"note_text": "updated note", "pinned": True},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["note_text"] == "updated note"
    assert data["pinned"] is True


@pytest.mark.asyncio
async def test_patch_bookmark_not_found(client: AsyncClient) -> None:
    """Patching a non-existent bookmark returns 404."""
    response = await client.patch(
        f"/api/v1/bookmarks/{uuid.uuid4()}",
        json={"note_text": "x"},
    )
    assert response.status_code == 404
