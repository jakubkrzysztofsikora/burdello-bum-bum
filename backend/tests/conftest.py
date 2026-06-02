"""Shared pytest fixtures for the Burdello Bum-Bum test suite.

Provides async event loop, database session with automatic rollback,
and an HTTP async client for FastAPI endpoint testing.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import Settings, get_settings
from backend.core.database import get_db
from backend.core.models import Base
from backend.main import create_app

# ---------------------------------------------------------------------------
# Test database URL (shared in-memory or temp PostgreSQL)
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "postgresql+asyncpg://bbuser:bbpass@localhost:5432/burdello_test"

# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a single event loop for the entire test session.

    Overrides pytest-asyncio's default loop-per-function to avoid
    "loop is closed" errors between async fixtures.

    Yields:
        The shared asyncio event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return test-specific settings.

    Returns:
        Settings with the test database URL.
    """
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        QDRANT_URL="http://localhost:6333",
        QDRANT_COLLECTION=f"test_chunks_{uuid.uuid4().hex[:8]}",
        REDIS_URL="redis://localhost:6379/15",  # DB 15 for tests
        CELERY_BROKER_URL="redis://localhost:6379/15",
        BB_LOG_LEVEL="DEBUG",
    )


# ---------------------------------------------------------------------------
# Test engine + schema creation
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_settings: Settings) -> AsyncGenerator:
    """Create a test database engine and initialise all tables.

    Yields:
        The async engine instance.
    """
    engine = create_async_engine(
        test_settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test database session with automatic rollback
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(
    test_engine,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session that is rolled back after each test.

    Wraps each test in a transaction that is always rolled back, ensuring
    test isolation and no side effects between tests.

    Yields:
        An async SQLAlchemy session.
    """
    async_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with test_engine.connect() as connection:
        transaction = await connection.begin()

        session = async_session_factory(bind=connection)

        yield session

        await session.close()
        await transaction.rollback()


# ---------------------------------------------------------------------------
# FastAPI test app with overridden dependencies
# ---------------------------------------------------------------------------


@pytest.fixture
def test_app(
    test_settings: Settings,
    db_session: AsyncSession,
) -> FastAPI:
    """Create a FastAPI test app with overridden dependencies.

    Args:
        test_settings: Test-specific settings.
        db_session: The per-test database session.

    Returns:
        Configured FastAPI application for testing.
    """
    app = create_app()

    # Override get_db to yield the test session
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: test_settings

    return app


# ---------------------------------------------------------------------------
# HTTP async client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(
    test_app: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTPX async client for the test app.

    Args:
        test_app: The FastAPI test application.

    Yields:
        An AsyncClient bound to the test app.
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
