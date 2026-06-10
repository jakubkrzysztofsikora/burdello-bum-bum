"""REST surface for the MCP tool functions.

Bearer-authenticated routes that mirror :mod:`backend.mcp_tools`. Used by the
Cloudflare Worker bridge for Claude.ai. The stdio MCP server (Claude Code)
calls the tool functions directly, so it does NOT need to go through this
router.

Bearer token comes from the ``MCP_BRIDGE_TOKEN`` env var. If unset, all
routes 503; this prevents an accidentally-exposed instance from leaking
data without explicit configuration.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.mcp_tools import (
    get_kanban_board,
    get_stats,
    list_artifacts,
    list_projects,
    list_tasks,
    search_transcripts,
    update_task_status,
)


router = APIRouter(prefix="/mcp", tags=["mcp"])


async def _require_bearer(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Reject requests without a valid bearer token.

    Returns 503 when ``MCP_BRIDGE_TOKEN`` isn't configured so the route is
    not silently open. Returns 401 on missing/wrong token.
    """
    expected = os.environ.get("MCP_BRIDGE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP bridge not configured (MCP_BRIDGE_TOKEN unset)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    if authorization[len("Bearer "):] != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Unauthenticated probe so the Worker can detect tunnel availability."""
    return {"ok": True, "service": "burdello-mcp"}


@router.post("/get_kanban_board", dependencies=[Depends(_require_bearer)])
async def call_get_kanban_board(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await get_kanban_board(
        db,
        project_name=body.get("project_name"),
        project_id=body.get("project_id"),
        limit_per_column=int(body.get("limit_per_column", 50)),
    )


@router.post("/update_task_status", dependencies=[Depends(_require_bearer)])
async def call_update_task_status(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task_id = body.get("task_id")
    new_status = body.get("new_status")
    if not task_id or not new_status:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id and new_status are required",
        )
    return await update_task_status(db, task_id=task_id, new_status=new_status)


@router.post("/list_projects", dependencies=[Depends(_require_bearer)])
async def call_list_projects(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await list_projects(
        db,
        search=body.get("search"),
        limit=int(body.get("limit", 50)),
    )


@router.post("/list_tasks", dependencies=[Depends(_require_bearer)])
async def call_list_tasks(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await list_tasks(
        db,
        project_id=body.get("project_id"),
        project_name=body.get("project_name"),
        status=body.get("status"),
        priority=body.get("priority"),
        limit=int(body.get("limit", 50)),
    )


@router.post("/list_artifacts", dependencies=[Depends(_require_bearer)])
async def call_list_artifacts(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await list_artifacts(
        db,
        project_id=body.get("project_id"),
        artifact_type=body.get("artifact_type"),
        limit=int(body.get("limit", 50)),
    )


@router.post("/search_transcripts", dependencies=[Depends(_require_bearer)])
async def call_search_transcripts(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await search_transcripts(
        db,
        query=body.get("query", ""),
        limit=int(body.get("limit", 10)),
    )


@router.post("/get_stats", dependencies=[Depends(_require_bearer)])
async def call_get_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await get_stats(db)
