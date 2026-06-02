"""API router for Search endpoints.

Provides hybrid vector search, similar transcript lookup, autocomplete
suggestions, and facet counts.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.models import Project, Source, Task, Transcript
from backend.core.schemas import SearchRequest, SearchResponse
from backend.search.engine import HybridSearchEngine

router = APIRouter(prefix="/search", tags=["search"])

# Module-level singleton (mirrors main.py pattern)
_settings = get_settings()
_search_engine: HybridSearchEngine | None = None


def _get_search_engine() -> HybridSearchEngine:
    """Get or create the search engine singleton."""
    global _search_engine
    if _search_engine is None:
        _search_engine = HybridSearchEngine(
            qdrant_url=_settings.QDRANT_URL,
            collection_name=_settings.QDRANT_COLLECTION,
        )
    return _search_engine


@router.post("/", response_model=SearchResponse)
async def search(
    request: SearchRequest,
) -> dict[str, Any]:
    """Execute a hybrid vector + filter search.

    Args:
        request: Search request with query, filters, limit, and offset.

    Returns:
        Search response with total count, query, and results.

    Raises:
        HTTPException: 500 if search engine error occurs.
    """
    engine = _get_search_engine()

    try:
        filters = request.filters.model_dump(exclude_none=True) if request.filters else None
        results = await engine.search(
            query=request.query,
            filters=filters,
            limit=request.limit,
            offset=request.offset,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search engine error: {exc!s}",
        )

    return {
        "total": len(results),
        "query": request.query,
        "results": results,
    }


@router.get("/similar/{transcript_id}")
async def find_similar(
    transcript_id: str,
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    """Find transcripts similar to the given one.

    Uses the first chunk of the reference transcript to find
    nearest neighbours in vector space.

    Args:
        transcript_id: UUID of the reference transcript.
        limit: Maximum number of similar transcripts.

    Returns:
        Dict with ``results`` (list of similar items).

    Raises:
        HTTPException: 500 if search engine error, 422 if invalid UUID.
    """
    try:
        uuid.UUID(transcript_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {transcript_id}",
        )

    engine = _get_search_engine()

    try:
        results = await engine.find_similar(transcript_id=transcript_id, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search engine error: {exc!s}",
        )

    return {
        "transcript_id": transcript_id,
        "results": results,
    }


@router.get("/suggest")
async def autocomplete(
    q: str = Query(..., min_length=2, max_length=100, description="Search prefix"),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, list[dict[str, Any]]]:
    """Return matching project names and task titles for autocomplete.

    Args:
        q: Search prefix (minimum 2 characters).
        db: Async database session.
        limit: Maximum suggestions per category.

    Returns:
        Dict with ``projects`` and ``tasks`` keys containing matches.
    """
    search_filter = f"%{q}%"

    # Search projects
    project_result = await db.execute(
        select(Project)
        .where(Project.name.ilike(search_filter))
        .limit(limit)
    )
    projects = [
        {"id": str(p.id), "name": p.name, "type": "project"}
        for p in project_result.scalars().all()
    ]

    # Search tasks
    task_result = await db.execute(
        select(Task)
        .where(Task.title.ilike(search_filter))
        .limit(limit)
    )
    tasks = [
        {"id": str(t.id), "title": t.title, "type": "task", "status": t.status}
        for t in task_result.scalars().all()
    ]

    return {"projects": projects, "tasks": tasks}


@router.get("/facets")
async def get_facets(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return facet counts grouped by project, status, and provider.

    Args:
        db: Async database session.

    Returns:
        Dict with ``by_status``, ``by_provider``, and ``by_project`` counts.
    """
    # Status facet (transcripts)
    status_result = await db.execute(
        select(Transcript.status, func.count(Transcript.id))
        .group_by(Transcript.status)
    )
    by_status = {status: count for status, count in status_result.all()}

    # Provider facet (source types)
    provider_result = await db.execute(
        select(Source.source_type, func.count(Source.id))
        .group_by(Source.source_type)
    )
    by_provider = {provider: count for provider, count in provider_result.all()}

    # Project facet
    project_result = await db.execute(
        select(Project.name, func.count(Task.id))
        .outerjoin(Task, Task.project_id == Project.id)
        .group_by(Project.id, Project.name)
    )
    by_project = {name: count for name, count in project_result.all()}

    return {
        "by_status": by_status,
        "by_provider": by_provider,
        "by_project": by_project,
    }
