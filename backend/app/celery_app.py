"""Celery application bootstrap for future background jobs."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "ai_study_assistant",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.document_tasks"],
)
