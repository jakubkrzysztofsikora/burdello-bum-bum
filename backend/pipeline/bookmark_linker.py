"""Event-driven linking of agent bookmarks to their ingested transcripts.

A :class:`~backend.core.models.Bookmark` is created with a raw ``session_id``
but no ``transcript_id`` — the transcript for that session may not have been
ingested yet. Once the pipeline finishes ingesting a session, the linker
back-fills ``transcript_id`` for every unlinked bookmark of that session in a
single set-based UPDATE (no per-row Python loop).

Keyed on ``session_id`` (a UUID), not on path strings, so it is filesystem- and
Docker-independent (see plan R2/R3).
"""

from __future__ import annotations

import logging

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Bookmark, Transcript

logger = logging.getLogger(__name__)


async def link_bookmarks_for_session(db: AsyncSession, session_id: str) -> int:
    """Point bookmarks for ``session_id`` at its newest transcript.

    Finds the most-recently-created :class:`Transcript` carrying ``session_id``
    and points every bookmark of that session at it (back-filling unlinked rows
    AND re-pointing rows still attached to an older/partial transcript of the
    same session), marking them ``ingest_status="linked"``. One set-based
    UPDATE.

    Re-pointing matters for re-ingest (plan R3 / Risk "partial-then-full"): a
    bookmark created mid-session links to the partial transcript first; when the
    grown file is later ingested as a newer transcript, this re-links it to the
    fuller one. The ``IS DISTINCT FROM`` guard keeps it idempotent — re-running
    once a bookmark already points at the newest transcript updates 0 rows.

    This is a pure function over the supplied session — it does NOT commit; the
    caller owns the transaction.

    Args:
        db: Active async session (caller commits).
        session_id: Agent session UUID to link bookmarks for.

    Returns:
        Number of bookmark rows updated (0 if ``session_id`` is falsy, no
        transcript exists yet, or every bookmark already points at the newest).
    """
    if not session_id:
        return 0

    transcript = (
        await db.execute(
            select(Transcript)
            .where(Transcript.session_id == session_id)
            .order_by(desc(Transcript.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    if transcript is None:
        return 0

    result = await db.execute(
        update(Bookmark)
        .where(
            Bookmark.session_id == session_id,
            # Link unlinked rows AND re-point rows on an older transcript of the
            # same session; no-op once already on the newest (idempotent).
            Bookmark.transcript_id.is_distinct_from(transcript.id),
        )
        .values(transcript_id=transcript.id, ingest_status="linked")
    )

    return result.rowcount or 0
