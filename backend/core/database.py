"""Async SQLAlchemy database engine and session management.

Provides ``create_async_engine``, ``async_sessionmaker``, dependency injection
for FastAPI routes, and an ``init_db`` helper to create all tables.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from backend.core.config import get_settings
from backend.core.models import Base

_settings = get_settings()

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

# NullPool: do not reuse asyncpg connections across event loops. The Celery
# pipeline tasks each run `asyncio.run(...)` (a fresh loop per task), and a
# pooled connection bound to a previous loop raises
# "got Future attached to a different loop". NullPool opens/closes a fresh
# connection per session within the current loop, which is correct for both
# the single-loop API process and the prefork Celery workers.
async_engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for FastAPI dependency injection.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    Yields:
        AsyncSession: A SQLAlchemy async session bound to the request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Init helper
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all database tables if they do not exist.

    Should be called once during application startup.  Tables are created
    via ``Base.metadata.create_all`` using the async engine.
    """
    async with async_engine.begin() as conn:
        # pgvector must exist before create_all builds VECTOR columns.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
