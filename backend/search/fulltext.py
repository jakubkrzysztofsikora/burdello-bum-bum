"""PostgreSQL full-text search utilities.

Provides functions to search ``messages`` and ``transcripts`` using
PostgreSQL's built-in ``to_tsvector`` / ``to_tsquery`` / ``ts_rank``
capabilities with GIN-index-friendly queries.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from sqlalchemy import Float as SAFloat
from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Message, Transcript

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", Message, Transcript)

# ---------------------------------------------------------------------------
# FTS helpers
# ---------------------------------------------------------------------------


def _normalise_query(raw_query: str) -> str:
    """Normalise a raw user query into a tsquery-safe string.

    Replaces non-alphanumeric characters with spaces and joins tokens
    with `` & `` so that PostgreSQL treats them as an AND query.

    Args:
        raw_query: The raw user-provided search string.

    Returns:
        A sanitised query string suitable for ``to_tsquery``.
    """
    tokens = [t for t in raw_query.split() if t]
    return " & ".join(tokens)


# ---------------------------------------------------------------------------
# Public search functions
# ---------------------------------------------------------------------------


async def search_messages(
    query: str,
    db: AsyncSession,
    limit: int = 50,
) -> list[Message]:
    """Full-text search over the ``messages`` table.

    Uses a GIN-index-friendly ``@@`` operator against a ``to_tsvector``
    built from the ``content`` column. Results are ordered by ``ts_rank_cd``
    descending.

    Args:
        query: Free-text search query.
        db: Active async SQLAlchemy session.
        limit: Maximum number of results to return.

    Returns:
        Ordered list of ``Message`` objects (best match first).
    """
    ts_query = func.plainto_tsquery("english", query)

    rank = func.ts_rank_cd(
        func.to_tsvector("english", Message.content),
        ts_query,
    ).label("rank")

    stmt: Select = (
        select(Message, rank)
        .where(
            func.to_tsvector("english", Message.content).op("@@")(ts_query)
        )
        .order_by(rank.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    logger.info(
        "search_messages: query=%r returned=%d",
        query,
        len(rows),
    )
    return [row[0] for row in rows]


async def search_transcripts(
    query: str,
    db: AsyncSession,
    limit: int = 50,
) -> list[Transcript]:
    """Full-text search over the ``transcripts`` table.

    Searches both the ``title`` and ``raw_text`` columns, returning the
    higher rank of the two per row.

    Args:
        query: Free-text search query.
        db: Active async SQLAlchemy session.
        limit: Maximum number of results to return.

    Returns:
        Ordered list of ``Transcript`` objects (best match first).
    """
    ts_query = func.plainto_tsquery("english", query)

    title_vec = func.to_tsvector("english", func.coalesce(Transcript.title, ""))
    text_vec = func.to_tsvector("english", func.coalesce(Transcript.raw_text, ""))
    combined_vec = title_vec.op("||")(text_vec)

    rank = func.ts_rank_cd(combined_vec, ts_query).label("rank")

    stmt: Select = (
        select(Transcript, rank)
        .where(combined_vec.op("@@")(ts_query))
        .order_by(rank.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    logger.info(
        "search_transcripts: query=%r returned=%d",
        query,
        len(rows),
    )
    return [row[0] for row in rows]


async def search_messages_raw(
    query: str,
    db: AsyncSession,
    limit: int = 50,
) -> list[Message]:
    """ILIKE-based fallback search for messages (no full-text index needed).

    Useful when ``to_tsvector`` indexes are not yet built or for
    substring matching.

    Args:
        query: Free-text search query.
        db: Active async SQLAlchemy session.
        limit: Maximum number of results.

    Returns:
        List of matching ``Message`` objects ordered by creation time.
    """
    pattern = f"%{query}%"
    stmt = (
        select(Message)
        .where(Message.content.ilike(pattern))
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
