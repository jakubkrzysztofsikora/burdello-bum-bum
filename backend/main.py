"""FastAPI application entry point for Burdello Bum-Bum.

Assembles all routers, configures CORS, initialises the database and
vector search collection on startup, and exposes health / stats endpoints.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.database import get_db, init_db
from backend.core.models import (
    Artifact,
    Project,
    Source,
    Task,
    Transcript,
)
from backend.core.schemas import HealthResponse, StatsResponse
from backend.search.engine import HybridSearchEngine

logger = logging.getLogger(__name__)
_settings = get_settings()

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------

search_engine = HybridSearchEngine(
    qdrant_url=_settings.QDRANT_URL,
    collection_name=_settings.QDRANT_COLLECTION,
)

# ---------------------------------------------------------------------------
# Routers (imported lazily to avoid circular imports at module level)
# ---------------------------------------------------------------------------


def _register_routers(app: FastAPI) -> None:
    """Attach all API routers to the FastAPI application."""
    from backend.api.routers.artifacts import router as artifacts_router
    from backend.api.routers.projects import router as projects_router
    from backend.api.routers.search import router as search_router
    from backend.api.routers.skills import router as skills_router
    from backend.api.routers.sources import router as sources_router
    from backend.api.routers.stats import router as stats_router
    from backend.api.routers.tasks import router as tasks_router
    from backend.api.routers.transcripts import router as transcripts_router

    app.include_router(sources_router, prefix="/api/v1")
    app.include_router(transcripts_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    app.include_router(artifacts_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(skills_router, prefix="/api/v1")
    app.include_router(stats_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan handler.

    *Startup* — creates database tables and ensures the Qdrant collection
    exists.

    *Shutdown* — cleans up engine connections.
    """
    logger.info("[startup] Initialising database tables ...")
    await init_db()

    logger.info(
        "[startup] Ensuring Qdrant collection %r ...",
        _settings.QDRANT_COLLECTION,
    )
    await search_engine.ensure_collection()

    logger.info("[startup] Burdello Bum-Bum ready!")
    yield

    logger.info("[shutdown] Cleaning up ...")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured ``FastAPI`` instance with all routers and middleware.
    """
    app = FastAPI(
        title="Burdello Bum-Bum",
        description="AI session transcript processing system",
        version="1.0.0",
        lifespan=lifespan,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers ---
    _register_routers(app)

    return app


app = create_app()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """Return application health status."""
    return HealthResponse(status="ok")


@app.get("/api/v1/stats", response_model=StatsResponse, tags=["system"])
async def get_stats(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    """Return global platform statistics.

    Counts rows in the major tables: sources, transcripts, projects,
    tasks, artifacts, and chunks.
    """
    tables = [
        ("sources_count", Source),
        ("transcripts_count", Transcript),
        ("projects_count", Project),
        ("tasks_count", Task),
        ("artifacts_count", Artifact),
    ]

    stats: dict[str, Any] = {"chunks_count": 0}

    for key, model in tables:
        result = await db.execute(select(func.count(model.id)))
        stats[key] = result.scalar() or 0

    return StatsResponse(**stats)
