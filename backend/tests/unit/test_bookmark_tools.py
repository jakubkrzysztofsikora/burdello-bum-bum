"""Unit tests for the bookmark MCP tool functions.

These call the tool functions in :mod:`backend.mcp_tools` directly with the
``db_session`` fixture — NOT through the bearer-guarded REST router (which 503s
when ``MCP_BRIDGE_TOKEN`` is unset). ``process_source.delay`` is patched so no
real Celery/Redis broker is required.

Coverage:
- a ``cwd`` under a known repo derives the canonical project via the path
  resolver (humanized name, not the raw dir name),
- a broker outage on focused ingest leaves the bookmark saved with
  ``ingest_status="failed"`` and raises nothing,
- a session that already has a transcript links immediately (no ingest),
- an unknown ``project_name`` with no path returns an error and creates no row,
- ``list_bookmarks`` returns the project's bookmarks pinned + newest first and
  mutates nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from kombu.exceptions import OperationalError

from backend.core.models import Bookmark, Source, Transcript
from backend.mcp_tools import create_bookmark, list_bookmarks
from backend.pipeline.repo_resolver import resolve_from_path

pytestmark = pytest.mark.unit

# A real-ish Claude Code session path. The resolver keys on the
# "/.claude/projects/-<encoded>/" segment (encoded = absolute repo dir with
# "/" -> "-"), exactly what the stdio server injects as session_path. It
# humanizes "burdello-bum-bum" -> "Burdello Bum Bum"; tests assert on that
# canonical name, NOT the raw directory.
_ENCODED = "-Users-x-Repos-personal-burdello-bum-bum"
_SESSION_PATH = f"/Users/x/.claude/projects/{_ENCODED}/sess.jsonl"


class _FakeJob:
    """Stand-in for a Celery AsyncResult (only ``.id`` is used)."""

    id = "job-123"


async def test_create_bookmark_derives_canonical_project_from_path(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session path under a repo resolves to the canonical project name."""
    monkeypatch.setattr(
        "backend.mcp_tools.process_source.delay",
        lambda *a, **k: _FakeJob(),
    )

    identity = resolve_from_path(_SESSION_PATH)
    assert identity is not None  # sanity: resolver matches the path

    result = await create_bookmark(
        db_session,
        note_text="revisit auth retry logic",
        session_path=_SESSION_PATH,
    )

    assert "error" not in result
    bm = result["bookmark"]
    assert bm["note_text"] == "revisit auth retry logic"

    # Project was get-or-created under the HUMANIZED name, not the raw dir.
    project_id = bm["project_id"]
    assert project_id is not None
    from backend.core.models import Project

    project = (
        await db_session.execute(
            select(Project).where(Project.id == project_id)
        )
    ).scalar_one()
    assert project.name == identity.humanized
    assert project.name != "burdello-bum-bum"

    # session_path is not a real file on disk → focused ingest not triggered.
    assert result["ingest_triggered"] is False


async def test_create_bookmark_broker_down_marks_failed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Broker outage during focused ingest → bookmark saved, status failed."""

    def _raise(*_a, **_k):
        raise OperationalError("broker down")

    monkeypatch.setattr("backend.mcp_tools.process_source.delay", _raise)

    # A real session file whose path also resolves via the path resolver
    # (must contain the "/.claude/projects/-<encoded>/" segment) so both
    # project resolution and the focused-ingest branch are reached.
    proj_dir = tmp_path / ".claude" / "projects" / _ENCODED
    proj_dir.mkdir(parents=True)
    session_file = proj_dir / "sess-broker.jsonl"
    session_file.write_text("{}\n")

    result = await create_bookmark(
        db_session,
        note_text="check this later",
        session_id="sess-broker",
        session_path=str(session_file),
    )

    assert "error" not in result
    bm = result["bookmark"]
    assert bm["ingest_status"] == "failed"
    assert result["ingest_triggered"] is False

    # Row persisted despite the broker failure.
    count = (
        await db_session.execute(
            select(func.count(Bookmark.id)).where(
                Bookmark.id == bm["id"]
            )
        )
    ).scalar_one()
    assert count == 1


async def test_create_bookmark_links_existing_transcript(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A session with an existing transcript links immediately, no ingest."""
    delay_calls: list = []
    monkeypatch.setattr(
        "backend.mcp_tools.process_source.delay",
        lambda *a, **k: delay_calls.append(a) or _FakeJob(),
    )

    source = Source(source_type="claude_code")
    db_session.add(source)
    await db_session.flush()
    transcript = Transcript(source_id=source.id, session_id="sess-linked")
    db_session.add(transcript)
    await db_session.flush()

    # Provide a real, resolver-matching file too, to prove the immediate link
    # short-circuits the focused ingest.
    proj_dir = tmp_path / ".claude" / "projects" / _ENCODED
    proj_dir.mkdir(parents=True)
    session_file = proj_dir / "sess-linked.jsonl"
    session_file.write_text("{}\n")

    result = await create_bookmark(
        db_session,
        note_text="already ingested",
        session_id="sess-linked",
        session_path=str(session_file),
    )

    bm = result["bookmark"]
    assert bm["transcript_id"] == str(transcript.id)
    assert bm["ingest_status"] == "linked"
    assert result["ingest_triggered"] is False
    assert delay_calls == []  # ingest NOT triggered


async def test_create_bookmark_unknown_project_no_path(
    db_session: AsyncSession,
) -> None:
    """Unknown project_name with no path/cwd → error, no row created."""
    before = (
        await db_session.execute(select(func.count(Bookmark.id)))
    ).scalar_one()

    result = await create_bookmark(
        db_session,
        note_text="orphan note",
        project_name="does-not-exist-project",
    )

    assert "error" in result
    assert "bookmark" not in result

    after = (
        await db_session.execute(select(func.count(Bookmark.id)))
    ).scalar_one()
    assert after == before


async def test_create_bookmark_derives_project_from_bare_cwd(
    db_session: AsyncSession,
) -> None:
    """A bare cwd (not a session_path) resolves to the canonical project."""
    result = await create_bookmark(
        db_session,
        note_text="bare cwd note",
        cwd="/Users/jakubsikora/Repos/personal/burdello-bum-bum",
    )
    assert "error" not in result, result["error"]
    bm = result["bookmark"]
    assert bm["project_id"] is not None
    from backend.core.models import Project
    project = (
        await db_session.execute(
            select(Project).where(Project.id == bm["project_id"])
        )
    ).scalar_one()
    assert project.name == "Burdello Bum Bum"


async def test_create_bookmark_note_text_validation(
    db_session: AsyncSession,
) -> None:
    """Empty or too-long note_text returns an error, no row."""
    before = (
        await db_session.execute(select(func.count(Bookmark.id)))
    ).scalar_one()

    empty = await create_bookmark(db_session, note_text="")
    assert "error" in empty
    assert "empty" in empty["error"].lower()

    long = await create_bookmark(db_session, note_text="x" * 4001)
    assert "error" in long
    assert "4000" in long["error"]

    after = (
        await db_session.execute(select(func.count(Bookmark.id)))
    ).scalar_one()
    assert after == before


async def test_create_bookmark_enc_computation_matches_real_dir(
    db_session: AsyncSession,
) -> None:
    """The encoding used by the stdio server matches the real path on disk."""
    import os
    from pathlib import Path

    cwd = os.getcwd()
    enc = cwd.replace("/", "-")
    real_dir = Path.home() / ".claude" / "projects" / enc
    assert real_dir.is_dir(), (
        f"Computed dir {real_dir} does not match the real .claude layout. "
        f"This means the encoding rule (replace '/' with '-') is wrong. "
    )


async def test_list_bookmarks_pinned_then_newest_pure_read(
    db_session: AsyncSession,
) -> None:
    """list_bookmarks returns pinned+newest first and mutates nothing."""
    from backend.core.models import Project

    project = Project(name="Bookmark List Test")
    db_session.add(project)
    await db_session.flush()

    base = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    older = Bookmark(
        project_id=project.id,
        note_text="older unpinned",
        created_at=base,
        pinned=False,
        ingest_status="none",
    )
    newer = Bookmark(
        project_id=project.id,
        note_text="newer unpinned",
        created_at=base + timedelta(hours=1),
        pinned=False,
        ingest_status="none",
    )
    pinned = Bookmark(
        project_id=project.id,
        note_text="pinned old",
        created_at=base - timedelta(hours=1),
        pinned=True,
        ingest_status="none",
    )
    db_session.add_all([older, newer, pinned])
    await db_session.flush()

    result = await list_bookmarks(db_session, project_id=str(project.id))

    assert result["project"]["id"] == str(project.id)
    assert result["count"] == 3
    notes = [item["note_text"] for item in result["items"]]
    # Pinned first, then unpinned newest-first.
    assert notes == ["pinned old", "newer unpinned", "older unpinned"]

    # Pure read: ingest_status untouched on every row.
    rows = (
        await db_session.execute(
            select(Bookmark).where(Bookmark.project_id == project.id)
        )
    ).scalars().all()
    assert all(r.ingest_status == "none" for r in rows)
    assert all(r.transcript_id is None for r in rows)
