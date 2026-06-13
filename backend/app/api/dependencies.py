"""FastAPI dependency wiring.

Constructs the service graph (storage + enqueue + JobsService) and exposes it to
routes via `Depends`. The enqueue function is the only point that touches Celery,
keeping the rest of the API free of broker concerns.
"""

from __future__ import annotations

from functools import lru_cache

from app.api.services.jobs_service import JobsService
from app.config import get_settings
from app.storage import build_storage


@lru_cache
def _storage():
    # `get_settings()` is itself cached, so the storage backend is built once.
    return build_storage(get_settings())


def _enqueue(job_id: str) -> None:
    # Imported lazily so importing the API does not pull in the worker module.
    from app.worker.tasks import orchestrate_job

    orchestrate_job.delay(job_id)


def get_jobs_service() -> JobsService:
    return JobsService(get_settings(), _storage(), _enqueue)
