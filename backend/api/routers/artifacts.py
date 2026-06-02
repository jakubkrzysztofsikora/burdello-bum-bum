"""API router for Artifact endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
