"""Tests for the Skills API router.

Covers skill listing and skill testing endpoints.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# List Skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_skills(client: AsyncClient) -> None:
    """Listing skills returns the built-in skill set."""
    response = await client.get("/api/v1/skills/")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 5

    # Verify expected skills are present
    skill_names = {s["name"] for s in data}
    expected = {"summarizer", "topic_extractor", "sentiment_analyzer", "action_item_miner", "entity_extractor"}
    assert expected.issubset(skill_names)

    # Verify skill structure
    for skill in data:
        assert "name" in skill
        assert "version" in skill
        assert "display_name" in skill
        assert "description" in skill
        assert "enabled" in skill


@pytest.mark.asyncio
async def test_list_skills_includes_disabled(client: AsyncClient) -> None:
    """Listing skills includes both enabled and disabled skills."""
    response = await client.get("/api/v1/skills/")
    assert response.status_code == 200

    data = response.json()
    enabled = [s for s in data if s["enabled"]]
    disabled = [s for s in data if not s["enabled"]]

    assert len(enabled) >= 4
    assert len(disabled) >= 1


# ---------------------------------------------------------------------------
# Test Skill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_skill_not_found(client: AsyncClient) -> None:
    """Testing a non-existent skill returns 404."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Test content")
        temp_path = f.name

    try:
        response = await client.post(
            "/api/v1/skills/test/nonexistent_skill?file_path=" + temp_path
        )
        assert response.status_code == 404
    finally:
        Path(temp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_test_skill_file_not_found(client: AsyncClient) -> None:
    """Testing against a non-existent file returns 404."""
    response = await client.post(
        "/api/v1/skills/test/summarizer?file_path=/nonexistent/path/file.txt"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_test_skill_success(client: AsyncClient) -> None:
    """Testing an existing skill against a valid file returns preview."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("This is a test transcript content for skill testing.")
        temp_path = f.name

    try:
        response = await client.post(
            f"/api/v1/skills/test/summarizer?file_path={temp_path}"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["skill"] == "summarizer"
        assert data["file_path"] == temp_path
        assert "preview" in data
        assert "extraction" in data
        assert data["file_size_bytes"] > 0
    finally:
        Path(temp_path).unlink(missing_ok=True)
