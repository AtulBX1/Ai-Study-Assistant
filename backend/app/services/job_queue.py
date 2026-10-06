"""Background job queue interface and runtime-specific implementations."""

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from fastapi import BackgroundTasks


class JobQueue(Protocol):
    """Queue a named application job with serializable arguments."""

    def enqueue(self, task_name: str, *args: Any, **kwargs: Any) -> None:
        """Schedule a registered job."""


class LocalJobQueue:
    """Run registered jobs after the current FastAPI response is sent."""

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        handlers: Mapping[str, Callable[..., Any]],
    ) -> None:
        self._background_tasks = background_tasks
        self._handlers = handlers

    def enqueue(self, task_name: str, *args: Any, **kwargs: Any) -> None:
        try:
            handler = self._handlers[task_name]
        except KeyError as error:
            raise ValueError(f"Unknown local background task: {task_name}") from error
        self._background_tasks.add_task(handler, *args, **kwargs)


class CeleryJobQueue:
    """Dispatch jobs to a Celery broker in production mode."""

    def __init__(self, celery_app: Any) -> None:
        self._celery_app = celery_app

    def enqueue(self, task_name: str, *args: Any, **kwargs: Any) -> None:
        self._celery_app.send_task(task_name, args=list(args), kwargs=kwargs)


def create_job_queue(
    background_tasks: BackgroundTasks | None = None,
    handlers: Mapping[str, Callable[..., Any]] | None = None,
) -> JobQueue:
    """Select FastAPI BackgroundTasks locally or Celery in production."""
    from app.core.config import get_settings

    if get_settings().backend == "local":
        if background_tasks is None:
            raise ValueError("background_tasks is required for BACKEND=local.")
        return LocalJobQueue(background_tasks, handlers or {})

    from app.celery_app import celery_app

    return CeleryJobQueue(celery_app)
