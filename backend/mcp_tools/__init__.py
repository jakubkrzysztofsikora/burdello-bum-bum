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

from typing import Any

from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Artifact, Project, Task, Transcript


_KANBAN_COLUMNS: tuple[str, ...] = ("todo", "in_progress", "done", "cancelled")
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
# Helpers
# ---------------------------------------------------------------------------


def _task_summary(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "description": (t.description or "")[:400],
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
