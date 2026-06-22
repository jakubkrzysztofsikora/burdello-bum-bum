"""API router for Bookmark endpoints.

Provides list, create, delete, and patch operations for agent-authored
bookmarks. Reads are pure (no linker side effects); linking is handled
event-driven off the ingest pipeline (see backend/pipeline/bookmark_linker.py).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.models import Bookmark
from backend.core.schemas import (
    BookmarkCreate,
    BookmarkListResponse,
    BookmarkResponse,
    BookmarkUpdate,
)

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("/", response_model=BookmarkListResponse)
async def list_bookmarks(
    db: AsyncSession = Depends(get_db),
    project_id: uuid.UUID | None = Query(None, description="Filter by project ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """List bookmarks, pinned + newest first.

    Pure read — never mutates rows. Bookmark/transcript linking happens
    event-driven in the ingest pipeline, not on read.

    Args:
        db: Async database session.
        project_id: Optional project filter.
        skip: Pagination offset.
        limit: Maximum items to return.

    Returns:
        Paginated list of bookmarks ({total, items}).
    """
    base_query = select(Bookmark)
    count_query = select(func.count(Bookmark.id))

    if project_id is not None:
        base_query = base_query.where(Bookmark.project_id == project_id)
        count_query = count_query.where(Bookmark.project_id == project_id)

    total = (await db.execute(count_query)).scalar() or 0

    base_query = (
        base_query.order_by(desc(Bookmark.pinned), desc(Bookmark.created_at))
        .offset(skip)
        .limit(limit)
    )
    items = (await db.execute(base_query)).scalars().all()

    return {"total": total, "items": items}


@router.post("/", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark_api(
    data: BookmarkCreate,
    db: AsyncSession = Depends(get_db),
) -> Bookmark:
    """Create a bookmark.

    Args:
        data: Bookmark creation payload.
        db: Async database session.

    Returns:
        Created bookmark.
    """
    bookmark = Bookmark(
        project_id=data.project_id,
        session_id=data.session_id,
        session_path=data.session_path,
        note_text=data.note_text,
        author=data.author,
        tags=data.tags,
        pinned=bool(data.pinned),
        metadata_=data.metadata,
    )
    db.add(bookmark)
    await db.commit()
    await db.refresh(bookmark)
    return bookmark


@router.patch("/{bookmark_id}", response_model=BookmarkResponse)
async def update_bookmark(
    bookmark_id: uuid.UUID,
    data: BookmarkUpdate,
    db: AsyncSession = Depends(get_db),
) -> Bookmark:
    """Update a bookmark's note_text, pinned, and/or tags.

    Only provided fields are applied (others left unchanged).

    Args:
        bookmark_id: UUID of the bookmark.
        data: Update payload.
        db: Async database session.

    Returns:
        Updated bookmark.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(select(Bookmark).where(Bookmark.id == bookmark_id))
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bookmark with ID {bookmark_id} not found",
        )

    fields = data.model_dump(exclude_unset=True)
    if fields.get("note_text") is not None:
        # note_text is NOT NULL; ignore an explicit null rather than letting it
        # reach the column and raise a 500. Empty strings are already rejected
        # by BookmarkUpdate's min_length=1 validator.
        bookmark.note_text = fields["note_text"]
    if "pinned" in fields and fields["pinned"] is not None:
        bookmark.pinned = bool(fields["pinned"])
    if "tags" in fields:
        bookmark.tags = fields["tags"]

    await db.commit()
    await db.refresh(bookmark)
    return bookmark


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a bookmark.

    Args:
        bookmark_id: UUID of the bookmark.
        db: Async database session.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(select(Bookmark).where(Bookmark.id == bookmark_id))
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bookmark with ID {bookmark_id} not found",
        )

    await db.delete(bookmark)
    await db.commit()
