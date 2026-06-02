"""API router for Ingestion endpoints.

Provides endpoints to trigger source discovery, handle file uploads,
and check ingestion queue status.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.pipeline.discovery import SourceDiscovery
from backend.pipeline.tasks import process_source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# In-memory status tracker (replace with Redis in production)
_ingest_status: dict[str, Any] = {}


@router.post("/")
async def trigger_ingest(
    background_tasks: BackgroundTasks,
    directories: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger source discovery and queue processing.

    Discovers transcript files in the configured directories and
    queues them for background processing.

    Args:
        background_tasks: FastAPI background tasks.
        directories: Optional dict with a ``paths`` key listing
            directories to scan. Defaults to current directory.

    Returns:
        Dict with job ID and number of discovered sources.
    """
    dir_list = directories.get("paths", ["."]) if directories else ["."]
    discovery = SourceDiscovery(directories=dir_list)

    sources = await discovery.discover()

    job_id = f"ingest_{uuid.uuid4().hex[:8]}"
    _ingest_status[job_id] = {
        "status": "queued",
        "total": len(sources),
        "processed": 0,
        "failed": 0,
        "sources": [s["file_path"] for s in sources],
    }

    logger.info("Ingest job %s: discovered %d sources", job_id, len(sources))

    return {
        "job_id": job_id,
        "discovered": len(sources),
        "directories": dir_list,
        "sources": sources,
    }


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
        "status": "uploaded",
        "message": "File uploaded successfully. Processing queued.",
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
