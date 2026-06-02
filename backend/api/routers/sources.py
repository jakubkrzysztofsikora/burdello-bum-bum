"""API router for Source CRUD endpoints.

Provides list, retrieve, and delete operations for transcript sources.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.models import Source, Transcript
from backend.core.schemas import (
    SourceListResponse,
    SourceResponse,
)

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/", response_model=SourceListResponse)
async def list_sources(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum items to return"),
    source_type: str | None = Query(None, description="Filter by source type"),
    search: str | None = Query(None, description="Search in title/description"),
) -> dict[str, Any]:
    """List all sources with optional filtering and pagination.

    Args:
        db: Async database session.
        skip: Number of items to skip for pagination.
        limit: Maximum number of items to return.
        source_type: Optional filter by source type (youtube, audio_file, etc.).
        search: Optional text search across title and description.

    Returns:
        Dict with ``items`` (list of sources) and ``total`` (count).
    """
    base_query = select(Source)
    count_query = select(func.count(Source.id))

    # Apply filters
    if source_type:
        base_query = base_query.where(Source.source_type == source_type)
        count_query = count_query.where(Source.source_type == source_type)

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(
            (Source.title.ilike(search_filter))
            | (Source.description.ilike(search_filter))
        )
        count_query = count_query.where(
            (Source.title.ilike(search_filter))
            | (Source.description.ilike(search_filter))
        )

    # Execute count query
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Execute paginated query
    base_query = base_query.offset(skip).limit(limit).order_by(Source.created_at.desc())
    result = await db.execute(base_query)
    items = result.scalars().all()

    return {"items": items, "total": total}


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> Source:
    """Get a single source by ID.

    Args:
        source_id: UUID of the source to retrieve.
        db: Async database session.

    Returns:
        The ``Source`` model instance.

    Raises:
        HTTPException: 404 if the source is not found.
    """
    try:
        source_uuid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {source_id}",
        )

    result = await db.execute(select(Source).where(Source.id == source_uuid))
    source = result.scalar_one_or_none()

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source with ID {source_id} not found",
        )

    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a source and all its related transcripts (cascade).

    Args:
        source_id: UUID of the source to delete.
        db: Async database session.

    Raises:
        HTTPException: 404 if the source is not found.
    """
    try:
        source_uuid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {source_id}",
        )

    result = await db.execute(select(Source).where(Source.id == source_uuid))
    source = result.scalar_one_or_none()

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source with ID {source_id} not found",
        )

    await db.delete(source)
    await db.commit()
