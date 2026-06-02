"""API router for Skills endpoints.

Lists available AI skills and provides a test endpoint for running
skills against files.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/")
async def list_skills() -> list[dict[str, Any]]:
    """List all available AI skills with metadata.

    Returns:
        List of skill dicts with name, version, display_name,
        description, and enabled status.
    """
    registry = SkillRegistry()
    return [
        {
            "name": s.name,
            "version": s.version,
            "display_name": s.display_name,
            "description": s.description,
            "enabled": s.enabled,
        }
        for s in registry.skills
    ]


@router.post("/test/{skill_name}")
async def test_skill(
    skill_name: str,
    file_path: str = Query(..., description="Absolute path to a file to test against"),
) -> dict[str, Any]:
    """Test a skill against a file and return an extraction preview.

    Args:
        skill_name: Name of the skill to test.
        file_path: Absolute path to the file to analyze.

    Returns:
        Dict with skill name, file path, and preview results.

    Raises:
        HTTPException: 404 if skill not found or file not found.
    """
    registry = SkillRegistry()
    skill = registry.get_skill(skill_name)

    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_name}' not found",
        )

    if not os.path.isfile(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file_path}",
        )

    # Read file preview (first 2000 chars)
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            preview = f.read(2000)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading file: {exc!s}",
        )

    logger.info("Testing skill %s against %s", skill_name, file_path)

    # Placeholder extraction preview
    return {
        "skill": skill_name,
        "file_path": file_path,
        "file_size_bytes": os.path.getsize(file_path),
        "preview_length": len(preview),
        "preview": preview[:500],
        "extraction": {
            "status": "preview_only",
            "note": "Full extraction requires LiteLLM integration",
        },
    }
