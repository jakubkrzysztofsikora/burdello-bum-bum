"""Application configuration using Pydantic Settings.

Provides environment-aware configuration for the Burdello Bum-Bum backend,
including database, vector store, Redis, Celery, and embedding settings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via environment variables with the same name.
    Default values are provided for local development.
    """

    # --- PostgreSQL ---
    DATABASE_URL: str = (
        "postgresql+asyncpg://bbuser:bbpass@localhost:5432/burdello"
    )

    # --- Qdrant Vector Store ---
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "burdello_chunks"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- LiteLLM Proxy ---
    LITELLM_URL: str = "http://localhost:4000"
    LITELLM_API_KEY: str = ""

    # --- Todoist ---
    TODOIST_API_TOKEN: str = ""

    # --- Celery ---
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # --- Application ---
    BB_LOG_LEVEL: str = "INFO"
    BB_EMBEDDING_MODEL: str = "nomic-embed-text-v2"
    BB_CHUNK_SIZE: int = 512
    BB_CHUNK_OVERLAP: int = 50

    class Config:
        """Pydantic config."""

        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Using ``lru_cache`` ensures the settings object is created only once
    per process, avoiding repeated environment parsing.

    Returns:
        Settings: The application settings singleton.
    """
    return Settings()
