"""Transcript stitching logic for the Celery pipeline."""

from __future__ import annotations

import time
from datetime import datetime

from app.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import JOB_LATENCY, JOBS_COMPLETED, JOBS_FAILED, JOBS_IN_FLIGHT
from app.domain.models import Chunk
from app.worker.repository import JobRepository
from app.worker.services.media.stitch import stitch_chunks

logger = get_logger(__name__)


def select_job_language(
    chunks: list[Chunk], default_language: str | None
) -> str | None:
    for chunk in sorted(chunks, key=lambda c: c.index):
        if chunk.language:
            return chunk.language
    return default_language


def run_stitch(job_id: str) -> None:
    """Combine completed chunks into the final transcript (claimed exactly once)."""
    settings = get_settings()
    repo = JobRepository(settings)
    try:
        job = repo.get(job_id)
        if job is None:
            logger.error(
                "Job vanished before stitch",
                extra={"fields": {"job_id": job_id}},
            )
            return
        repo.mark_stitching(job_id)
        logger.info(
            "Stitching chunks",
            extra={"fields": {"job_id": job_id, "chunks": len(job.chunks)}},
        )
        t0 = time.perf_counter()
        text, segments = stitch_chunks(job.chunks)
        logger.info(
            "Stitch complete",
            extra={"fields": {
                "job_id": job_id,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "segments": len(segments),
                "words": len(text.split()),
            }},
        )
        detected_language = select_job_language(job.chunks, settings.whisper_language)
        if repo.mark_completed(
            job_id, text=text, segments=segments, language=detected_language
        ):
            JOBS_COMPLETED.inc()
            created = job.created_at.replace(tzinfo=None)
            JOB_LATENCY.observe((datetime.utcnow() - created).total_seconds())
            JOBS_IN_FLIGHT.dec()
    except Exception as exc:
        logger.exception("Stitch failed", extra={"fields": {"job_id": job_id}})
        if repo.mark_failed(job_id, error=f"stitch: {exc}"):
            JOBS_FAILED.labels(reason="stitch").inc()
            JOBS_IN_FLIGHT.dec()
