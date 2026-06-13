"""Maintenance jobs for worker-owned job state."""

from __future__ import annotations

from app.config import get_settings
from app.core.metrics import REAPER_FAILED_JOBS, REAPER_RUNS
from app.worker.repository import JobRepository


def run_stuck_job_reaper() -> int:
    """Fail PROCESSING jobs whose worker heartbeat has gone stale."""
    settings = get_settings()
    repo = JobRepository(settings)
    failed_jobs = repo.fail_stuck_jobs(settings.stuck_job_timeout_seconds)
    REAPER_RUNS.inc()
    if failed_jobs:
        REAPER_FAILED_JOBS.inc(failed_jobs)
    return failed_jobs
