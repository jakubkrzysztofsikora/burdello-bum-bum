"""Unit tests for :mod:`backend.pipeline.bookmark_linker`.

Covers the session_id-keyed, set-based bookmark linker:
- a matching session links the newest transcript and flips ingest_status,
- no transcript for the session is a no-op,
- with multiple transcripts for one session, the newest wins,
- re-ingest (partial-then-full) re-points an already-linked bookmark to the
  newer transcript (plan R3),
- re-running once a bookmark is on the newest transcript is idempotent (0 rows).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Bookmark, Source, Transcript
from backend.pipeline.bookmark_linker import link_bookmarks_for_session

pytestmark = pytest.mark.unit


async def _make_source(db: AsyncSession) -> Source:
    source = Source(source_type="claude_code")
    db.add(source)
    await db.flush()
    return source


async def test_links_newest_transcript_for_session(
    db_session: AsyncSession,
) -> None:
    """A session_id match links the transcript and sets ingest_status."""
    source = await _make_source(db_session)
    transcript = Transcript(source_id=source.id, session_id="sess-1")
    db_session.add(transcript)
    await db_session.flush()

    bookmark = Bookmark(session_id="sess-1", note_text="revisit auth retry")
    db_session.add(bookmark)
    await db_session.flush()

    linked = await link_bookmarks_for_session(db_session, "sess-1")
    assert linked == 1

    await db_session.refresh(bookmark)
    assert bookmark.transcript_id == transcript.id
    assert bookmark.ingest_status == "linked"


async def test_no_transcript_for_session_is_noop(
    db_session: AsyncSession,
) -> None:
    """When no transcript carries the session_id, nothing is linked."""
    bookmark = Bookmark(session_id="sess-orphan", note_text="dangling note")
    db_session.add(bookmark)
    await db_session.flush()

    linked = await link_bookmarks_for_session(db_session, "sess-orphan")
    assert linked == 0

    await db_session.refresh(bookmark)
    assert bookmark.transcript_id is None
    assert bookmark.ingest_status == "none"


async def test_picks_newest_of_multiple_transcripts(
    db_session: AsyncSession,
) -> None:
    """With two transcripts for one session, link to the newest by created_at."""
    source = await _make_source(db_session)
    base = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    older = Transcript(
        source_id=source.id, session_id="sess-2", created_at=base
    )
    newer = Transcript(
        source_id=source.id,
        session_id="sess-2",
        created_at=base + timedelta(hours=1),
    )
    db_session.add_all([older, newer])
    await db_session.flush()

    bookmark = Bookmark(session_id="sess-2", note_text="deferred refactor")
    db_session.add(bookmark)
    await db_session.flush()

    linked = await link_bookmarks_for_session(db_session, "sess-2")
    assert linked == 1

    await db_session.refresh(bookmark)
    assert bookmark.transcript_id == newer.id


async def test_reingest_relinks_to_newer_transcript(
    db_session: AsyncSession,
) -> None:
    """Partial-then-full re-ingest re-points a linked bookmark to the newer one.

    A bookmark created mid-session first links to the partial transcript; when
    the grown file is later ingested as a newer transcript for the same session,
    the linker re-points it (plan R3 / Risk "partial-then-full").
    """
    source = await _make_source(db_session)
    base = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    partial = Transcript(source_id=source.id, session_id="sess-3", created_at=base)
    db_session.add(partial)
    await db_session.flush()

    # Bookmark already linked to the partial transcript.
    bookmark = Bookmark(
        session_id="sess-3",
        note_text="design question",
        transcript_id=partial.id,
        ingest_status="linked",
    )
    db_session.add(bookmark)
    await db_session.flush()

    # Grown file ingested → a newer transcript for the same session.
    full = Transcript(
        source_id=source.id,
        session_id="sess-3",
        created_at=base + timedelta(hours=1),
    )
    db_session.add(full)
    await db_session.flush()

    linked = await link_bookmarks_for_session(db_session, "sess-3")
    assert linked == 1

    await db_session.refresh(bookmark)
    assert bookmark.transcript_id == full.id
    assert bookmark.ingest_status == "linked"


async def test_relink_is_idempotent_on_newest(
    db_session: AsyncSession,
) -> None:
    """Re-running once a bookmark already points at the newest is a no-op."""
    source = await _make_source(db_session)
    transcript = Transcript(source_id=source.id, session_id="sess-4")
    db_session.add(transcript)
    await db_session.flush()

    bookmark = Bookmark(
        session_id="sess-4",
        note_text="verify later",
        transcript_id=transcript.id,
        ingest_status="linked",
    )
    db_session.add(bookmark)
    await db_session.flush()

    # Already on the newest (and only) transcript → IS DISTINCT FROM matches 0.
    linked = await link_bookmarks_for_session(db_session, "sess-4")
    assert linked == 0

    await db_session.refresh(bookmark)
    assert bookmark.transcript_id == transcript.id


async def test_falsy_session_id_returns_zero(
    db_session: AsyncSession,
) -> None:
    """An empty session_id short-circuits to 0 without a query."""
    assert await link_bookmarks_for_session(db_session, "") == 0
