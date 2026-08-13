"""Tool functions exposed via MCP (Model Context Protocol).

Each function returns a JSON-serialisable dict so the same code path can be
called from:

- the FastAPI router `backend/api/routers/mcp_api.py` (Cloudflare Worker
  bridge for Claude.ai),
- the stdio MCP server `backend/mcp/stdio_server.py` (Claude Code).

Functions are intentionally small; complex business logic stays in
`backend/api/routers/*` or the storage layer so the MCP surface is just a
thin re-shape for tool calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kombu.exceptions import OperationalError
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import (
    Artifact,
    Bookmark,
    KbEntity,
    KbEntityMention,
    KbNode,
    KbNodeSource,
    Project,
    Task,
    Transcript,
)
from backend.pipeline.bookmark_linker import link_bookmarks_for_session
from backend.pipeline.repo_resolver import resolve_from_cwd, resolve_from_path
from backend.pipeline.tasks import process_source


_KANBAN_COLUMNS: tuple[str, ...] = ("todo", "in_progress", "done", "cancelled")
_MAX_NOTE_LEN: int = 4000
_KANBAN_LABELS: dict[str, str] = {
    "todo": "Todo",
    "in_progress": "In Progress",
    "done": "Done",
    "cancelled": "Cancelled",
}


# ---------------------------------------------------------------------------
# Kanban
# ---------------------------------------------------------------------------


async def get_kanban_board(
    db: AsyncSession,
    *,
    project_name: str | None = None,
    project_id: str | None = None,
    limit_per_column: int = 50,
) -> dict[str, Any]:
    """Return a kanban view of one project's tasks.

    Either ``project_name`` or ``project_id`` must be provided. ``project_name``
    is a case-insensitive exact match against ``Project.name``.
    """
    if not project_id and not project_name:
        raise ValueError("get_kanban_board: provide project_name or project_id")

    project_q = select(Project)
    if project_id:
        project_q = project_q.where(Project.id == project_id)
    else:
        project_q = project_q.where(func.lower(Project.name) == project_name.lower())

    project = (await db.execute(project_q)).scalar_one_or_none()
    if project is None:
        return {
            "project": None,
            "columns": [],
            "error": f"project not found: {project_name or project_id}",
        }

    rows = (
        await db.execute(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(
                case(
                    (Task.priority == "urgent", 0),
                    (Task.priority == "high", 1),
                    (Task.priority == "medium", 2),
                    (Task.priority == "low", 3),
                    else_=4,
                ),
                desc(Task.created_at),
            )
        )
    ).scalars().all()

    columns: dict[str, list[dict[str, Any]]] = {c: [] for c in _KANBAN_COLUMNS}
    for t in rows:
        bucket = t.status if t.status in columns else "todo"
        if len(columns[bucket]) >= limit_per_column:
            continue
        columns[bucket].append(_task_summary(t))

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
        },
        "columns": [
            {
                "key": c,
                "label": _KANBAN_LABELS[c],
                "tasks": columns[c],
                "count": len(columns[c]),
            }
            for c in _KANBAN_COLUMNS
        ],
        "total_tasks": sum(len(v) for v in columns.values()),
    }


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


_VALID_TASK_STATUSES = {"todo", "in_progress", "done", "cancelled"}


async def update_task_status(
    db: AsyncSession,
    *,
    task_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Move a single task to a new column."""
    if new_status not in _VALID_TASK_STATUSES:
        raise ValueError(
            f"update_task_status: invalid status {new_status!r}; "
            f"valid: {sorted(_VALID_TASK_STATUSES)}"
        )

    task = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        return {"updated": False, "reason": f"task not found: {task_id}"}

    previous = task.status
    task.status = new_status
    await db.flush()
    await db.commit()

    return {
        "updated": True,
        "task_id": str(task.id),
        "title": task.title,
        "previous_status": previous,
        "new_status": new_status,
    }


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------


async def list_projects(
    db: AsyncSession,
    *,
    search: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Top N projects with task counts. Used by Claude to surface a menu."""
    base_q = (
        select(
            Project,
            func.count(Task.id).label("task_count"),
            func.coalesce(
                func.sum(case((Task.status == "done", 1), else_=0)), 0
            ).label("done_count"),
        )
        .outerjoin(Task, Task.project_id == Project.id)
        .group_by(Project.id)
        .order_by(desc("task_count"))
        .limit(limit)
    )
    if search:
        base_q = base_q.where(Project.name.ilike(f"%{search}%"))

    rows = (await db.execute(base_q)).all()
    return {
        "items": [
            {
                "id": str(p.id),
                "name": p.name,
                "notes": p.notes,
                "tags": p.tags or [],
                "pinned": p.pinned,
                "task_count": int(tc),
                "completed_task_count": int(dc),
            }
            for p, tc, dc in rows
        ],
        "count": len(rows),
    }


async def list_tasks(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    q = select(Task)
    if project_id:
        q = q.where(Task.project_id == project_id)
    elif project_name:
        q = q.join(Project, Task.project_id == Project.id).where(
            func.lower(Project.name) == project_name.lower()
        )
    if status:
        q = q.where(Task.status == status)
    if priority:
        q = q.where(Task.priority == priority)
    q = q.order_by(desc(Task.created_at)).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    return {
        "items": [_task_summary(t) for t in rows],
        "count": len(rows),
    }


async def list_artifacts(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    artifact_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    q = select(Artifact)
    if project_id:
        q = q.where(Artifact.project_id == project_id)
    if artifact_type:
        q = q.where(Artifact.artifact_type == artifact_type)
    q = q.order_by(desc(Artifact.created_at)).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    return {
        "items": [
            {
                "id": str(a.id),
                "name": a.name,
                "artifact_type": a.artifact_type,
                "project_id": str(a.project_id) if a.project_id else None,
                "preview": ((a.content or {}).get("content_preview") or "")[:500],
                "notes": a.notes,
                "tags": a.tags or [],
                "pinned": a.pinned,
            }
            for a in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# Search + stats
# ---------------------------------------------------------------------------


async def search_transcripts(
    db: AsyncSession,
    *,
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Cheap title/raw-text ILIKE search. The richer vector search lives at
    /api/v1/search/; this is a quick fallback that doesn't need Qdrant."""
    needle = f"%{query}%"
    rows = (
        await db.execute(
            select(Transcript)
            .where(
                or_(
                    Transcript.title.ilike(needle),
                    Transcript.raw_text.ilike(needle),
                )
            )
            .order_by(desc(Transcript.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(t.id),
                "title": t.title or "",
                "preview": (t.raw_text or "")[:300],
            }
            for t in rows
        ],
        "count": len(rows),
    }


async def get_stats(db: AsyncSession) -> dict[str, Any]:
    counts = {}
    for label, model in [
        ("transcripts", Transcript),
        ("projects", Project),
        ("tasks", Task),
        ("artifacts", Artifact),
    ]:
        counts[label] = int(
            (await db.execute(select(func.count(model.id)))).scalar_one() or 0
        )
    return counts


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


async def create_bookmark(
    db: AsyncSession,
    *,
    note_text: str,
    session_id: str | None = None,
    session_path: str | None = None,
    cwd: str | None = None,
    project_name: str | None = None,
    project_id: str | None = None,
    author: str = "claude-code",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Persist a bookmark, deriving its project from the session path.

    Project resolution (R1): when a ``session_path`` or ``cwd`` is supplied, the
    project is *derived* from it via the canonical path resolver (the same one
    mining uses) and get-or-created by the humanized name. Otherwise it falls
    back to an explicit ``project_id``/``project_name`` for non-Claude-Code
    callers. Transcript linking keys on ``session_id`` (R2); a best-effort
    immediate link handles already-ingested sessions, and an unlinked bookmark
    with a real session file triggers a focused ingest (R3) — broker outages are
    swallowed so the bookmark is never lost.
    """
    if not note_text or not note_text.strip():
        return {"error": "note_text is required and must not be empty"}
    if len(note_text) > _MAX_NOTE_LEN:
        return {"error": f"note_text exceeds {_MAX_NOTE_LEN} characters"}

    # Derive the canonical project from the session path (preferred) or the bare
    # cwd, using the SAME resolver mining uses — so the bookmark lands on the
    # project this session will be classified as. session_path is an encoded
    # transcript path → resolve_from_path; cwd is a plain dir → resolve_from_cwd.
    identity = None
    if session_path:
        identity = resolve_from_path(session_path)
    if identity is None and cwd:
        identity = resolve_from_cwd(cwd)
    if identity is not None:
        project = await _get_or_create_project(db, identity.humanized)
    else:
        project = await _resolve_project(
            db, project_id=project_id, project_name=project_name
        )
    if project is None:
        return {
            "error": "could not resolve project (no path and unknown project_name)"
        }

    bm = Bookmark(
        project_id=project.id,
        session_id=session_id,
        session_path=session_path,
        note_text=note_text,
        author=author,
        tags=tags,
        ingest_status="none",
    )
    db.add(bm)
    await db.flush()

    linked = await link_bookmarks_for_session(db, session_id) if session_id else 0

    triggered = False
    if not linked and session_path and Path(session_path).is_file():
        try:
            job = process_source.delay(session_path)
            bm.ingest_job_id = job.id
            bm.ingest_status = "pending"
            triggered = True
        except OperationalError:
            # Broker down; the bookmark is already persisted — surface the
            # failure on the row instead of raising.
            bm.ingest_status = "failed"

    # Persist any post-insert status/job-id changes, then refresh so the row
    # reflects DB state: server defaults, ``created_at``, and the bulk linker's
    # UPDATE (which set ``transcript_id``/``ingest_status`` out of session).
    await db.flush()
    await db.refresh(bm)
    return {"bookmark": _bookmark_summary(bm), "ingest_triggered": triggered}


async def list_bookmarks(
    db: AsyncSession,
    *,
    project_name: str | None = None,
    project_id: str | None = None,
    cwd: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List a project's bookmarks, pinned + newest first. Pure read (no linker).

    Resolves the project from ``project_id``/``project_name`` first, then falls
    back to deriving it from ``cwd`` via the path resolver so a Claude Code
    session defaults to its current repo.
    """
    project = await _resolve_project(
        db, project_id=project_id, project_name=project_name
    )
    if project is None and cwd:
        # Bare cwd → canonical identity via the same resolver mining uses.
        identity = resolve_from_cwd(cwd)
        if identity is not None:
            project = await _resolve_project(
                db, project_name=identity.humanized
            )
    if project is None:
        return {
            "project": None,
            "items": [],
            "error": "could not resolve project (unknown project_name and no cwd match)",
        }

    rows = (
        await db.execute(
            select(Bookmark)
            .where(Bookmark.project_id == project.id)
            .order_by(desc(Bookmark.pinned), desc(Bookmark.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return {
        "project": {"id": str(project.id), "name": project.name},
        "items": [_bookmark_summary(b) for b in rows],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_project(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> Project | None:
    """Resolve a project by id, else by case-insensitive exact name.

    Mirrors the inline pattern the other MCP tools use. Returns ``None`` when
    neither lookup matches or both inputs are falsy.
    """
    if project_id:
        return (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
    if project_name:
        return (
            await db.execute(
                select(Project).where(
                    func.lower(Project.name) == project_name.lower()
                )
            )
        ).scalar_one_or_none()
    return None


async def _get_or_create_project(db: AsyncSession, name: str) -> Project:
    """Get a project by case-insensitive name, creating it if absent.

    Matches the get-or-create idiom in ``storage.py`` (de-dup by name); flushes
    so the caller has the id. The caller owns the transaction (no commit here).
    """
    existing = (
        await db.execute(
            select(Project).where(func.lower(Project.name) == name.lower())
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    project = Project(name=name)
    db.add(project)
    try:
        # Isolate in a SAVEPOINT: if a concurrent caller inserted the same name
        # first, Project.name's unique constraint trips here without poisoning
        # the outer transaction. Re-select the winner instead of losing the row.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        project = (
            await db.execute(
                select(Project).where(func.lower(Project.name) == name.lower())
            )
        ).scalar_one()
    return project


def _bookmark_summary(bm: Bookmark) -> dict[str, Any]:
    return {
        "id": str(bm.id),
        "project_id": str(bm.project_id) if bm.project_id else None,
        "transcript_id": str(bm.transcript_id) if bm.transcript_id else None,
        "session_id": bm.session_id,
        "session_path": bm.session_path,
        "note_text": bm.note_text,
        "author": bm.author,
        "ingest_status": bm.ingest_status,
        "ingest_job_id": bm.ingest_job_id,
        "tags": bm.tags or [],
        "pinned": bm.pinned,
        "created_at": bm.created_at.isoformat() if bm.created_at else None,
        "updated_at": bm.updated_at.isoformat() if bm.updated_at else None,
        "metadata": bm.metadata_ or {},
    }


def _task_summary(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "description": (t.description or "")[:400],
        "notes": t.notes,
        "tags": t.tags or [],
        "pinned": t.pinned,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------


_KB_TREE_MAX_DEPTH = 4


def _kb_node_summary(node: KbNode) -> dict[str, Any]:
    """Render one ``KbNode`` for tree-style responses."""
    return {
        "slug": node.slug,
        "title": node.title,
        "node_type": node.node_type,
        "parent_slug": node.parent.slug if node.parent else None,
        "status": node.status,
        "top_terms": list(node.top_terms or []),
        "confidence": float(node.confidence or 0.0),
        "source_evidence_count": node.source_evidence_count,
    }


async def kb_tree(
    db: AsyncSession,
    *,
    root_slug: str | None = None,
    max_depth: int = _KB_TREE_MAX_DEPTH,
    include_drafts: bool = False,
) -> dict[str, Any]:
    """Return the KB tree, optionally rooted at one category.

    Args:
        db: Async SQLAlchemy session.
        root_slug: Optional slug of a category node to start from. When
            ``None``, every published root category is returned.
        max_depth: Maximum recursion depth (root = 0). Cap at 4.
        include_drafts: When ``True``, draft (not-yet-published) nodes
            are included in the response.

    Returns:
        Dict with ``nodes`` (nested list) and ``total`` count.
    """
    depth_cap = max(0, min(max_depth, _KB_TREE_MAX_DEPTH))
    statuses = {"published", "draft"} if include_drafts else {"published"}

    base_filter = KbNode.status.in_(statuses)
    if root_slug:
        base_filter = base_filter & (KbNode.slug == root_slug)

    rows = (
        await db.execute(
            select(KbNode)
            .options(selectinload(KbNode.parent))
            .where(base_filter)
            .order_by(KbNode.node_type.desc(), KbNode.slug.asc())
        )
    ).scalars().all()

    if not rows:
        return {"nodes": [], "total": 0}

    slug_to_parent: dict[str, str | None] = {}
    for row in rows:
        slug_to_parent[row.slug] = row.parent.slug if row.parent else None

    node_map: dict[str, dict[str, Any]] = {
        row.slug: _kb_node_summary(row) for row in rows
    }
    for slug in node_map:
        node_map[slug]["children"] = []

    roots: list[dict[str, Any]] = []
    for row in rows:
        parent_slug = slug_to_parent.get(row.slug)
        if parent_slug is None:
            roots.append(node_map[row.slug])
        else:
            node_map[parent_slug]["children"].append(node_map[row.slug])

    def _truncate(node: dict[str, Any], depth: int) -> dict[str, Any]:
        if depth >= depth_cap:
            node["children"] = []
            return node
        node["children"] = [
            _truncate(child, depth + 1) for child in node["children"]
        ]
        return node

    trimmed = [_truncate(r, 0) for r in roots]
    return {"nodes": trimmed, "total": len(rows)}


async def kb_page_read(
    db: AsyncSession,
    slug: str,
) -> dict[str, Any]:
    """Return one KB page with its evidence and child pages.

    Args:
        db: Async SQLAlchemy session.
        slug: Node slug to read.

    Returns:
        Dict with ``node``, ``evidence`` (up to 25 items), and
        ``children`` (immediate sub-nodes). Empty ``node`` dict when
        the slug does not resolve.
    """
    node = (
        await db.execute(
            select(KbNode).where(KbNode.slug == slug)
        )
    ).scalar_one_or_none()
    if node is None:
        return {"node": {}, "evidence": [], "children": []}

    evidence_rows = (
        await db.execute(
            select(KbNodeSource)
            .where(KbNodeSource.node_id == node.id)
            .order_by(KbNodeSource.created_at.desc())
            .limit(25)
        )
    ).scalars().all()

    child_rows = (
        await db.execute(
            select(KbNode)
            .where(KbNode.parent_id == node.id)
            .order_by(KbNode.slug.asc())
        )
    ).scalars().all()

    node_payload = _kb_node_summary(node)
    node_payload.update(
        {
            "summary": node.summary,
            "mechanical_key": node.mechanical_key,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        }
    )

    return {
        "node": node_payload,
        "evidence": [
            {
                "id": str(e.id),
                "transcript_id": str(e.transcript_id) if e.transcript_id else None,
                "project_id": str(e.project_id) if e.project_id else None,
                "excerpt": e.excerpt,
                "outcome": e.outcome,
                "evidence_type": e.evidence_type,
                "confidence": e.confidence,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evidence_rows
        ],
        "children": [_kb_node_summary(c) for c in child_rows],
    }


async def kb_entity_lookup(
    db: AsyncSession,
    name: str,
    *,
    limit_mentions: int = 20,
) -> dict[str, Any]:
    """Look up a KB entity by canonical name or alias.

    Args:
        db: Async SQLAlchemy session.
        name: Canonical name or alias to search for (case-insensitive).
        limit_mentions: Maximum mention rows to return.

    Returns:
        Dict with ``entity`` and ``mentions``. Empty ``entity`` dict
        when nothing matches.
    """
    name_lc = name.strip().lower()
    if not name_lc:
        return {"entity": {}, "mentions": []}

    # Canonical-name match first; fall back to alias overlap with
    # case-insensitive comparison via a per-row EXISTS subquery.
    # ``select(...).exists()`` emits ``EXISTS (SELECT 1 ... FROM unnest(...))``
    # which Postgres evaluates against the outer kb_entities row.
    entity = (
        await db.execute(
            select(KbEntity).where(
                func.lower(KbEntity.canonical_name) == name_lc
            )
        )
    ).scalars().first()
    if entity is None:
        entity = (
            await db.execute(
                select(KbEntity)
                .where(
                    KbEntity.aliases.isnot(None),
                    select(
                        func.lower(func.unnest(KbEntity.aliases))
                    )
                    .where(
                        func.lower(func.unnest(KbEntity.aliases)) == name_lc
                    )
                    .exists(),
                )
            )
        ).scalars().first()

    if entity is None:
        return {"entity": {}, "mentions": []}

    mentions = (
        await db.execute(
            select(KbEntityMention)
            .where(KbEntityMention.entity_id == entity.id)
            .order_by(KbEntityMention.first_seen_at.desc().nullslast())
            .limit(limit_mentions)
        )
    ).scalars().all()

    return {
        "entity": {
            "id": str(entity.id),
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "description": entity.description,
            "how_used": entity.how_used,
            "why_used": entity.why_used,
            "mention_count": entity.mention_count,
            "aliases": list(entity.aliases or []),
        },
        "mentions": [
            {
                "id": str(m.id),
                "transcript_id": str(m.transcript_id) if m.transcript_id else None,
                "project_id": str(m.project_id) if m.project_id else None,
                "context_excerpt": m.context_excerpt,
                "outcome": m.outcome,
                "first_seen_at": m.first_seen_at.isoformat() if m.first_seen_at else None,
                "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
            }
            for m in mentions
        ],
    }
