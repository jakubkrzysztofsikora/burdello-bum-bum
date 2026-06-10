#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "mcp[cli]>=1.0",
#   "httpx>=0.27",
# ]
# ///
"""Burdello MCP server — stdio transport for Claude Code.

This file is a uv "PEP 723" script: it carries its own dependency
metadata so `uv run` (or `claude mcp add` invoking
`uv run --script /abs/path/to/this/file`) bootstraps an isolated venv on
first launch — no global install needed.

The server is a thin proxy over the bearer-authenticated REST routes at
``/api/v1/mcp/*`` on the local Burdello backend. The same Python tool
functions back both surfaces (see backend/mcp_tools/).

Environment:
    BURDELLO_API_URL   default ``http://localhost:8000``
    MCP_BRIDGE_TOKEN   required; matches the backend's env var
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("BURDELLO_API_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("MCP_BRIDGE_TOKEN", "").strip()
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _client() -> httpx.AsyncClient:
    if not TOKEN:
        # Surface the misconfiguration on every tool call so users see WHY
        # nothing works, instead of a generic "tool failed" in Claude.
        print(
            "burdello-mcp: MCP_BRIDGE_TOKEN env var is empty; set it to "
            "the value from burdello-bum-bum/.env",
            file=sys.stderr,
        )
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    return httpx.AsyncClient(base_url=f"{API_URL}/api/v1/mcp", headers=headers, timeout=TIMEOUT)


async def _call(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    async with _client() as c:
        r = await c.post(path, json=payload or {})
        r.raise_for_status()
        return r.json()


mcp = FastMCP("burdello")


@mcp.tool()
async def get_kanban_board(
    project_name: str | None = None,
    project_id: str | None = None,
    limit_per_column: int = 50,
) -> dict[str, Any]:
    """Return a kanban view of one project's tasks.

    Provide either ``project_name`` (case-insensitive exact match) or
    ``project_id``. Returns columns ``todo``, ``in_progress``, ``done``,
    ``cancelled`` with up to ``limit_per_column`` tasks each, ordered by
    priority then recency.
    """
    return await _call(
        "/get_kanban_board",
        {
            "project_name": project_name,
            "project_id": project_id,
            "limit_per_column": limit_per_column,
        },
    )


@mcp.tool()
async def update_task_status(task_id: str, new_status: str) -> dict[str, Any]:
    """Move a task to a new column.

    Valid statuses: ``todo``, ``in_progress``, ``done``, ``cancelled``.
    Use this after finishing a unit of work, or to revive a task from
    ``done`` back to ``in_progress``.
    """
    return await _call(
        "/update_task_status", {"task_id": task_id, "new_status": new_status}
    )


@mcp.tool()
async def list_projects(search: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Top projects by task volume; optional case-insensitive name search."""
    return await _call("/list_projects", {"search": search, "limit": limit})


@mcp.tool()
async def list_tasks(
    project_id: str | None = None,
    project_name: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List tasks. Filter by project (id or name), status, and priority."""
    return await _call(
        "/list_tasks",
        {
            "project_id": project_id,
            "project_name": project_name,
            "status": status,
            "priority": priority,
            "limit": limit,
        },
    )


@mcp.tool()
async def list_artifacts(
    project_id: str | None = None,
    artifact_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List artifacts (source_code, documentation, config, test, …)."""
    return await _call(
        "/list_artifacts",
        {
            "project_id": project_id,
            "artifact_type": artifact_type,
            "limit": limit,
        },
    )


@mcp.tool()
async def search_transcripts(query: str, limit: int = 10) -> dict[str, Any]:
    """Title + raw-text ILIKE search across all transcripts."""
    return await _call("/search_transcripts", {"query": query, "limit": limit})


@mcp.tool()
async def get_stats() -> dict[str, Any]:
    """Total counts of transcripts / projects / tasks / artifacts."""
    return await _call("/get_stats")


if __name__ == "__main__":
    mcp.run()
