"""API router for Ingestion endpoints.

Provides endpoints to trigger source discovery, handle file uploads,
and check ingestion queue status.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from kombu.exceptions import OperationalError

from backend.pipeline.discovery import DEFAULT_PROVIDER_PATTERNS, SourceDiscovery
from backend.pipeline.tasks import process_source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# In-memory status tracker (replace with Redis in production)
_ingest_status: dict[str, Any] = {}

# Session ids are filename stems; restrict to safe chars before globbing so a
# crafted value can't expand wildcards or traverse directories.
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,255}")


def _find_session_file(session_id: str | None) -> str | None:
    """Locate a provider session file by its session UUID.

    Session files are named ``<session_id>.jsonl``. The Claude Code layout
    (``~/.claude/projects/**/<session_id>.jsonl``) is by far the most common, so
    it is probed first; other providers from ``DEFAULT_PROVIDER_PATTERNS`` are a
    fallback. On collision (the same id under multiple dirs) the
    most-recently-modified file wins — that is the live session being appended
    to — so selection is deterministic across runs/hosts.

    Args:
        session_id: Agent session UUID (the file stem), or ``None``.

    Returns:
        Absolute path of the newest matching file, or ``None``.
    """
    if not session_id:
        return None

    # Validate the id before globbing: a value containing ``*``/``..``/``/``
    # would otherwise be glob-expanded and could walk the filesystem.
    if not _SESSION_ID_RE.fullmatch(session_id):
        return None

    home = Path.home()
    candidates: list[Path] = []

    # Most common: Claude Code sessions.
    candidates.extend(home.glob(f".claude/projects/**/{session_id}.jsonl"))

    # Fallback: other providers. session_id is the filename stem, so swap the
    # trailing ``*`` of each provider glob for ``<session_id>``.
    for pattern in DEFAULT_PROVIDER_PATTERNS.values():
        if pattern.endswith("*.jsonl"):
            candidate = pattern[: -len("*.jsonl")] + f"{session_id}.jsonl"
        elif pattern.endswith("*.json"):
            candidate = pattern[: -len("*.json")] + f"{session_id}.json"
        else:
            continue
        candidates.extend(home.glob(candidate))

    files = [p for p in candidates if p.is_file()]
    if not files:
        return None
    # Newest by mtime wins — deterministic and prefers the live/grown file.
    return str(max(files, key=lambda p: p.stat().st_mtime))


@router.post("/")
async def trigger_ingest() -> dict[str, Any]:
    """Trigger source discovery and queue processing.

    Discovers transcript files under the configured provider directories
    (defaulting to the user's home directory) and dispatches each to the
    Celery pipeline for background processing.

    Returns:
        Dict with job ID and number of discovered/queued sources.
    """
    discovery = SourceDiscovery()
    sources = discovery.discover()

    job_id = f"ingest_{uuid.uuid4().hex[:8]}"
    for source in sources:
        process_source.delay(source["path"], source.get("provider"))

    _ingest_status[job_id] = {
        "status": "queued",
        "total": len(sources),
        "processed": 0,
        "failed": 0,
        "sources": [s["path"] for s in sources],
    }

    logger.info("Ingest job %s: queued %d sources", job_id, len(sources))

    return {
        "job_id": job_id,
        "discovered": len(sources),
        "sources": [s["path"] for s in sources],
    }


@router.post("/session")
async def ingest_session(
    path: str | None = Query(None, description="Absolute path to a session file"),
    session_id: str | None = Query(None, description="Session UUID to locate"),
) -> dict[str, Any]:
    """Trigger focused ingest of a single agent session file.

    Accepts either an explicit ``path`` (preferred) or a ``session_id`` to look
    up. Dispatches the single-file pipeline to Celery.

    Returns:
        Dict with the Celery job id, resolved session path, and status.

    Raises:
        HTTPException: 422 if neither arg given, 404 if no file found,
            503 if the Celery broker is unavailable.
    """
    if not path and not session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="path or session_id required",
        )

    target = path or _find_session_file(session_id)
    if not target or not Path(target).is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session file not found",
        )

    try:
        result = process_source.delay(target)
    except OperationalError as exc:
        # Log the broker detail; don't leak connection strings to the client.
        logger.error("Ingest session: broker unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingest queue unavailable",
        )

    logger.info("Ingest session: queued %s (job=%s)", target, result.id)

    return {"job_id": result.id, "session_path": target, "status": "queued"}


@router.post("/upload")
async def upload_transcript(
    file: UploadFile = File(..., description="Transcript file to upload"),
) -> dict[str, Any]:
    """Save an uploaded file and process it through the pipeline.

    Args:
        file: Uploaded file.

    Returns:
        Dict with source ID, file path, and processing status.

    Raises:
        HTTPException: 400 if filename is missing, 500 if save fails.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename",
        )

    # Create upload directory
    upload_dir = Path(tempfile.gettempdir()) / "burdello_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate safe filename
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = upload_dir / safe_name

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {exc!s}",
        )
    finally:
        await file.close()

    file_size = file_path.stat().st_size
    source_id = uuid.uuid4()

    logger.info(
        "Uploaded file %s (%d bytes) -> %s",
        file.filename,
        file_size,
        file_path,
    )

    # Queue the uploaded file for pipeline processing
    try:
        result = process_source.delay(str(file_path))
    except OperationalError as exc:
        logger.error("Upload ingest: broker unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingest queue unavailable",
        )

    # Build source data for processing
    source_data = {
        "file_path": str(file_path),
        "source_type": "transcript_file",
        "title": Path(file.filename).stem,
        "metadata": {
            "original_filename": file.filename,
            "size_bytes": file_size,
            "content_type": file.content_type,
        },
    }

    return {
        "source_id": str(source_id),
        "file_path": str(file_path),
        "filename": file.filename,
        "size_bytes": file_size,
        "status": "queued",
        "message": "File uploaded successfully. Processing queued.",
        "celery_job_id": result.id,
        "source_data": source_data,
    }


@router.get("/status")
async def get_ingest_status(
    job_id: str | None = Query(None, description="Optional specific job ID"),
) -> dict[str, Any]:
    """Return ingestion queue status.

    Args:
        job_id: Optional job ID to get specific job status.

    Returns:
        Dict with queue status information.
    """
    if job_id and job_id in _ingest_status:
        return {"job": _ingest_status[job_id]}

    total_jobs = len(_ingest_status)
    total_sources = sum(j["total"] for j in _ingest_status.values())
    total_processed = sum(j["processed"] for j in _ingest_status.values())

    return {
        "total_jobs": total_jobs,
        "total_sources": total_sources,
        "total_processed": total_processed,
        "jobs": _ingest_status,
    }
