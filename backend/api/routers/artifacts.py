"""API router for Artifact endpoints.

Provides list and retrieve operations for AI-generated artifacts
with filtering by transcript, task, and type.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.models import Artifact
from backend.core.schemas import ArtifactListResponse, ArtifactResponse

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/", response_model=ArtifactListResponse)
async def list_artifacts(
    db: AsyncSession = Depends(get_db),
    transcript_id: str | None = Query(None, description="Filter by source transcript ID"),
    task_id: str | None = Query(None, description="Filter by related task ID"),
    artifact_type: str | None = Query(None, description="Filter by artifact type (summary, mind_map, etc.)"),
    search: str | None = Query(None, description="Search in artifact name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-created_at", description="Sort field, prefix with - for descending"),
) -> dict[str, Any]:
    """List artifacts with filtering, sorting, and pagination.

    Args:
        db: Async database session.
        transcript_id: Optional source transcript ID filter.
        task_id: Optional task ID filter (searches metadata).
        artifact_type: Optional artifact type filter.
        search: Optional text search on artifact name.
        skip: Pagination offset.
        limit: Maximum items to return.
        sort: Sort field with optional ``-`` prefix for descending.

    Returns:
        Paginated list of artifacts.
    """
    base_query = select(Artifact)
    count_query = select(func.count(Artifact.id))

    # Apply filters
    if artifact_type:
        base_query = base_query.where(Artifact.artifact_type == artifact_type)
        count_query = count_query.where(Artifact.artifact_type == artifact_type)

    if transcript_id:
        try:
            tid = uuid.UUID(transcript_id)
            base_query = base_query.where(Artifact.source_transcript_id == tid)
            count_query = count_query.where(Artifact.source_transcript_id == tid)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid transcript UUID: {transcript_id}",
            )

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(Artifact.name.ilike(search_filter))
        count_query = count_query.where(Artifact.name.ilike(search_filter))

    # Get total count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply sorting
    if sort.startswith("-"):
        sort_field = sort[1:]
        base_query = base_query.order_by(getattr(Artifact, sort_field, Artifact.created_at).desc())
    else:
        base_query = base_query.order_by(getattr(Artifact, sort, Artifact.created_at).asc())

    # Apply pagination
    base_query = base_query.offset(skip).limit(limit)

    result = await db.execute(base_query)
    items = list(result.scalars().all())

    page = skip // limit + 1 if limit > 0 else 1
    return {
        "total": total,
        "page": page,
        "page_size": limit,
        "items": items,
    }


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),
) -> Artifact:
    """Get a single artifact by ID.

    Args:
        artifact_id: UUID of the artifact.
        db: Async database session.

    Returns:
        The artifact.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        artifact_uuid = uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {artifact_id}",
        )

    result = await db.execute(select(Artifact).where(Artifact.id == artifact_uuid))
    artifact = result.scalar_one_or_none()

    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact with ID {artifact_id} not found",
        )

    return artifact


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an artifact.

    Args:
        artifact_id: UUID of the artifact to delete.
        db: Async database session.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        artifact_uuid = uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {artifact_id}",
        )

    result = await db.execute(select(Artifact).where(Artifact.id == artifact_uuid))
    artifact = result.scalar_one_or_none()

    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact with ID {artifact_id} not found",
        )

    await db.delete(artifact)
    await db.commit()
