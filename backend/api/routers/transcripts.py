"""API router for Transcript endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/transcripts", tags=["transcripts"])
