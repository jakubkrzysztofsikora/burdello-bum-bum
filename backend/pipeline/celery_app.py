"""Celery application for background task processing.

Initialises the Celery app with Redis as broker and provides
base configuration for task execution.
"""

from __future__ import annotations

from celery import Celery

from backend.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "burdello",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.REDIS_URL,
    include=[
        "backend.pipeline.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    # Don't let chain/task results linger in Redis for the 24h default — they
    # accumulate and pressure the broker. 30 min is ample for the pipeline.
    result_expires=1800,
)
