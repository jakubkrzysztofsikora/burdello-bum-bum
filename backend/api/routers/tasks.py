"""API router for Task endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/tasks", tags=["tasks"])
