"""Celery task entrypoints for the transcription pipeline.

    orchestrate_job ── plans chunks, then fans out ──┐
                                                     │  (Celery group)
        transcribe_chunk × N  (parallel, retried) ───┤
                                                     │  last one to finish
    stitch_results ◀── claimed atomically in Mongo ──┘  triggers the stitch

Coordination uses an atomic MongoDB claim (`try_claim_stitch`) instead of a
Celery chord, so no result backend is required — MongoDB stays the single
source of truth. The concrete work is delegated to focused modules; this file
only defines stable Celery task names and task-level limits/retry settings.
"""

from __future__ import annotations

from celery.signals import worker_process_init

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.worker.celery_app import celery_app
from app.worker.chunk_transcription import run_chunk_transcription
from app.worker.orchestration import run_orchestration
from app.worker.reaper import run_stuck_job_reaper
from app.worker.services.transcription import get_transcriber
from app.worker.stitching import run_stitch, select_job_language

logger = get_logger(__name__)
configure_logging()

_select_job_language = select_job_language


def _settings():
    return get_settings()


@worker_process_init.connect
def _preload_model(**_kwargs) -> None:
    """Load the Whisper model in every fork-pool process at startup."""
    try:
        get_transcriber(_settings())
        logger.info("Whisper model pre-loaded in worker process")
    except Exception:
        logger.exception("Failed to pre-load Whisper model — first task will be slow")


@celery_app.task(
    name="app.worker.tasks.orchestrate_job",
    soft_time_limit=60,
    time_limit=90,
)
def orchestrate_job(job_id: str) -> None:
    run_orchestration(job_id)


@celery_app.task(
    name="app.worker.tasks.transcribe_chunk",
    bind=True,
    max_retries=_settings().celery_max_retries,
    acks_late=True,
    soft_time_limit=360,
    time_limit=420,
)
def transcribe_chunk(
    self, job_id: str, index: int, start: float, end: float, storage_key: str
) -> int:
    return run_chunk_transcription(self, job_id, index, start, end, storage_key)


@celery_app.task(name="app.worker.tasks.stitch_results")
def stitch_results(job_id: str) -> None:
    run_stitch(job_id)


@celery_app.task(name="app.worker.tasks.reap_stuck_jobs")
def reap_stuck_jobs() -> int:
    return run_stuck_job_reaper()
