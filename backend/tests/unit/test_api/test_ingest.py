"""Tests for the Ingest API router.

Covers trigger ingest, file upload, and status endpoints.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Trigger Ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.routers.ingest.SourceDiscovery")
async def test_trigger_ingest(mock_discovery_cls, client: AsyncClient) -> None:
    """Triggering ingest discovers sources and returns a job."""
    mock_discovery = AsyncMock()
    mock_discovery.discover.return_value = [
        {"file_path": "/tmp/test1.txt", "source_type": "transcript_file", "title": "Test 1"},
        {"file_path": "/tmp/test2.txt", "source_type": "transcript_file", "title": "Test 2"},
    ]
    mock_discovery_cls.return_value = mock_discovery

    response = await client.post(
        "/api/v1/ingest/",
        json={"paths": ["/tmp/test_dir"]},
    )
    assert response.status_code == 200

    data = response.json()
    assert "job_id" in data
    assert data["discovered"] == 2
    assert data["directories"] == ["/tmp/test_dir"]
    assert len(data["sources"]) == 2


@pytest.mark.asyncio
@patch("backend.api.routers.ingest.SourceDiscovery")
async def test_trigger_ingest_empty(mock_discovery_cls, client: AsyncClient) -> None:
    """Triggering ingest with no sources returns zero discovered."""
    mock_discovery = AsyncMock()
    mock_discovery.discover.return_value = []
    mock_discovery_cls.return_value = mock_discovery

    response = await client.post("/api/v1/ingest/")
    assert response.status_code == 200

    data = response.json()
    assert data["discovered"] == 0


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_transcript(client: AsyncClient) -> None:
    """Uploading a transcript file returns source info."""
    content = b"This is a test transcript file content."

    response = await client.post(
        "/api/v1/ingest/upload",
        files={"file": ("test_transcript.txt", content, "text/plain")},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "uploaded"
    assert data["filename"] == "test_transcript.txt"
    assert data["size_bytes"] == len(content)
    assert "source_id" in data
    assert "file_path" in data

    # Clean up temp file
    file_path = Path(data["file_path"])
    if file_path.exists():
        file_path.unlink()


@pytest.mark.asyncio
async def test_upload_no_filename(client: AsyncClient) -> None:
    """Uploading without a filename returns 400."""
    response = await client.post(
        "/api/v1/ingest/upload",
        files={"file": ("", b"content", "text/plain")},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ingest_status_empty(client: AsyncClient) -> None:
    """Getting status when no jobs exist returns empty state."""
    response = await client.get("/api/v1/ingest/status")
    assert response.status_code == 200

    data = response.json()
    assert data["total_jobs"] == 0
    assert data["total_sources"] == 0


@pytest.mark.asyncio
@patch("backend.api.routers.ingest.SourceDiscovery")
async def test_get_ingest_status_with_job(mock_discovery_cls, client: AsyncClient) -> None:
    """Getting status after creating a job returns job info."""
    mock_discovery = AsyncMock()
    mock_discovery.discover.return_value = [
        {"file_path": "/tmp/test.txt", "source_type": "transcript_file", "title": "Test"},
    ]
    mock_discovery_cls.return_value = mock_discovery

    # Create a job
    response = await client.post("/api/v1/ingest/")
    data = response.json()
    job_id = data["job_id"]

    # Get status for specific job
    response = await client.get(f"/api/v1/ingest/status?job_id={job_id}")
    assert response.status_code == 200

    status_data = response.json()
    assert "job" in status_data
    assert status_data["job"]["total"] == 1
