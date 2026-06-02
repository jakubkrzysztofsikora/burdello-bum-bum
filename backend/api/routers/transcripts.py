"""API router for Transcript endpoints.

Provides list, retrieve, messages, and delete operations for transcripts
with filtering, sorting, and pagination.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.core.models import Message, MiningResult, Source, Transcript
from backend.core.schemas import (
    MessageResponse,
    TranscriptDetailResponse,
    TranscriptListResponse,
    TranscriptSummary,
)

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _clean_project_name(raw: str | None) -> str | None:
    """Turn a path-encoded project name into a readable repo name.

    ``-Users-jakubsikora-Repos-personal-sikoras-chat`` -> ``sikoras-chat``.
    """
    if not raw:
        return None
    name = raw
    if "-Repos-" in name:
        name = name.split("-Repos-")[-1]
        # drop the org segment (e.g. personal-, circit-)
        parts = name.split("-", 1)
        if len(parts) == 2 and parts[0] in {"personal", "circit", "work"}:
            name = parts[1]
    name = name.lstrip("-").strip()
    # Bare home paths aren't useful project names.
    if not name or name.startswith("Users"):
        return None
    return name


def _derive_title(transcript: Any, first_user_message: str | None) -> str:
    """Derive a human-readable session title from the transcript content.

    Prefers the opening user prompt; falls back to a cleaned project/repo name,
    then the filename.
    """
    text = (first_user_message or "").strip()
    # Codex stores structured content as a stringified list of ContentBlocks;
    # pull the readable text="..." segments out of it.
    if text.startswith("[") and "text=" in text:
        text = " ".join(re.findall(r'text=["\']([^"\']{4,}?)["\']', text))
    text = re.sub(r"<[^>]+>", " ", text)  # command/tool tags
    text = re.sub(r"```[a-zA-Z0-9]*", " ", text)  # code fences
    text = text.replace("\\n", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # Use the prompt only if it reads like a real request (not env dumps or
    # agent boilerplate).
    looks_clean = len(text) >= 8 and not re.match(
        r"(?i)^(# ?AGENTS|permissions|you are |/Users/|zsh\b|env\b)", text
    )
    if looks_clean:
        return text[:90] + ("…" if len(text) > 90 else "")

    pn = _clean_project_name((transcript.metadata_ or {}).get("project_name"))
    if pn:
        return pn
    title = (transcript.title or "").rsplit(".", 1)[0]
    return title or "Untitled session"


def _parse_sort(sort: str) -> tuple[str, bool]:
    """Parse a sort parameter into field name and direction.

    Args:
        sort: Sort string, e.g. ``-started_at`` or ``created_at``.

    Returns:
        Tuple of (field_name, ascending).
    """
    if sort.startswith("-"):
        return sort[1:], False
    return sort, True


@router.get("/", response_model=TranscriptListResponse)
async def list_transcripts(
    db: AsyncSession = Depends(get_db),
    project: str | None = Query(None, description="Filter by project ID"),
    status: str | None = Query(None, description="Filter by status (pending, processing, completed, error)"),
    provider: str | None = Query(None, description="Filter by source type/provider"),
    search: str | None = Query(None, description="Search in title"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    sort: str = Query("-created_at", description="Sort field, prefix with - for descending"),
) -> dict[str, Any]:
    """List transcripts with filtering, sorting, and pagination.

    Args:
        db: Async database session.
        project: Optional project ID filter.
        status: Optional status filter.
        provider: Optional source type filter.
        search: Optional text search in transcript title.
        skip: Pagination offset.
        limit: Maximum items to return.
        sort: Sort field, prefix with ``-`` for descending.

    Returns:
        Paginated list of transcript summaries.
    """
    base_query = select(Transcript).options(selectinload(Transcript.source))
    count_query = select(func.count(Transcript.id))

    # Apply filters
    if status:
        base_query = base_query.where(Transcript.status == status)
        count_query = count_query.where(Transcript.status == status)

    if provider:
        base_query = base_query.join(Source).where(Source.source_type == provider)
        count_query = count_query.join(Source).where(Source.source_type == provider)

    if project:
        # Filter by project ID in metadata
        base_query = base_query.where(
            Transcript.metadata_["project_id"].as_string() == project
        )
        count_query = count_query.where(
            Transcript.metadata_["project_id"].as_string() == project
        )

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(Transcript.title.ilike(search_filter))
        count_query = count_query.where(Transcript.title.ilike(search_filter))

    # Get total count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply sorting
    sort_field, ascending = _parse_sort(sort)
    sort_column = getattr(Transcript, sort_field, Transcript.created_at)
    if not ascending:
        sort_column = sort_column.desc()
    base_query = base_query.order_by(sort_column)

    # Apply pagination
    base_query = base_query.offset(skip).limit(limit)

    result = await db.execute(base_query)
    transcripts = list(result.scalars().all())
    transcript_ids = [t.id for t in transcripts]

    # Batch: message count per transcript.
    msg_counts: dict[Any, int] = {}
    # Batch: first user message per transcript (for a derived session title).
    first_user_msg: dict[Any, str] = {}
    if transcript_ids:
        cnt_rows = await db.execute(
            select(Message.transcript_id, func.count(Message.id))
            .where(Message.transcript_id.in_(transcript_ids))
            .group_by(Message.transcript_id)
        )
        msg_counts = {tid: int(c) for tid, c in cnt_rows.all()}

        fm_rows = await db.execute(
            select(Message.transcript_id, Message.content)
            .where(
                Message.transcript_id.in_(transcript_ids),
                Message.speaker == "user",
            )
            .order_by(Message.transcript_id, Message.sequence)
            .distinct(Message.transcript_id)
        )
        for tid, content in fm_rows.all():
            if content:
                first_user_msg[tid] = content

    items: list[TranscriptSummary] = []
    for transcript in transcripts:
        items.append(
            TranscriptSummary(
                id=transcript.id,
                title=_derive_title(transcript, first_user_msg.get(transcript.id)),
                status=transcript.status,
                message_count=msg_counts.get(transcript.id, 0),
                metadata=transcript.metadata_,
                created_at=transcript.created_at,
            )
        )

    page = skip // limit + 1 if limit > 0 else 1
    return {
        "total": total,
        "page": page,
        "page_size": limit,
        "items": items,
    }


@router.get("/{transcript_id}", response_model=TranscriptDetailResponse)
async def get_transcript(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
) -> Transcript:
    """Get a transcript with its messages and mining results.

    Args:
        transcript_id: UUID of the transcript.
        db: Async database session.

    Returns:
        The transcript with loaded relationships.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        transcript_uuid = uuid.UUID(transcript_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {transcript_id}",
        )

    result = await db.execute(
        select(Transcript)
        .options(
            selectinload(Transcript.source),
            selectinload(Transcript.messages),
            selectinload(Transcript.mining_results),
        )
        .where(Transcript.id == transcript_uuid)
    )
    transcript = result.scalar_one_or_none()

    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript with ID {transcript_id} not found",
        )

    return transcript


@router.get("/{transcript_id}/messages", response_model=list[MessageResponse])
async def get_transcript_messages(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Message]:
    """Get messages for a transcript with pagination.

    Args:
        transcript_id: UUID of the transcript.
        db: Async database session.
        skip: Pagination offset.
        limit: Maximum messages to return.

    Returns:
        List of messages ordered by sequence.

    Raises:
        HTTPException: 404 if transcript not found, 422 if invalid UUID.
    """
    try:
        transcript_uuid = uuid.UUID(transcript_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {transcript_id}",
        )

    # Verify transcript exists
    transcript_result = await db.execute(
        select(Transcript.id).where(Transcript.id == transcript_uuid)
    )
    if transcript_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript with ID {transcript_id} not found",
        )

    result = await db.execute(
        select(Message)
        .where(Message.transcript_id == transcript_uuid)
        .order_by(Message.sequence)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.delete("/{transcript_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transcript(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a transcript and all its messages/chunks (cascade).

    Args:
        transcript_id: UUID of the transcript to delete.
        db: Async database session.

    Raises:
        HTTPException: 404 if not found, 422 if invalid UUID.
    """
    try:
        transcript_uuid = uuid.UUID(transcript_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format: {transcript_id}",
        )

    result = await db.execute(select(Transcript).where(Transcript.id == transcript_uuid))
    transcript = result.scalar_one_or_none()

    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript with ID {transcript_id} not found",
        )

    await db.delete(transcript)
    await db.commit()
