"""Single-chunk transcription logic for the Celery pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from app.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import (
    CHUNKS_IN_PROGRESS,
    JOBS_FAILED,
    JOBS_IN_FLIGHT,
    TRANSCRIPTION_DURATION,
)
from app.domain.models import TranscriptSegment
from app.storage import build_storage
from app.worker.repository import JobRepository
from app.worker.services.media.ffmpeg import extract_window
from app.worker.services.transcription import get_transcriber

logger = get_logger(__name__)


def run_chunk_transcription(
    task: Any,
    job_id: str,
    index: int,
    start: float,
    end: float,
    storage_key: str,
) -> int:
    """Transcribe one window. Retries on transient errors; raises to fail-fast."""
    settings = get_settings()
    repo = JobRepository(settings)
    storage = build_storage(settings)
    transcriber = get_transcriber(settings)

    source = storage.local_path(storage_key)
    window_path = Path(storage.local_path(f"chunks/{job_id}/{index}.wav"))

    logger.info(
        "Chunk started",
        extra={"fields": {
            "job_id": job_id,
            "chunk": index,
            "window": f"{start:.1f}-{end:.1f}s",
            "duration_s": round(end - start, 2),
        }},
    )
    CHUNKS_IN_PROGRESS.inc()
    try:
        logger.debug(
            "Extracting audio window",
            extra={"fields": {
                "job_id": job_id, "chunk": index, "dest": str(window_path),
            }},
        )
        extract_window(
            source,
            window_path,
            start_seconds=start,
            duration_seconds=end - start,
            sample_rate=settings.audio_sample_rate,
        )
        logger.debug(
            "Audio window extracted — starting Whisper",
            extra={"fields": {"job_id": job_id, "chunk": index}},
        )
        t0 = time.perf_counter()
        result = transcriber.transcribe(window_path, language=settings.whisper_language)
        elapsed = time.perf_counter() - t0
        TRANSCRIPTION_DURATION.observe(elapsed)
        logger.info(
            "Chunk transcribed",
            extra={"fields": {
                "job_id": job_id, "chunk": index,
                "elapsed_s": round(elapsed, 2),
                "segments": len(result.segments),
                "language": result.language,
                "preview": (result.text[:80] + "…") if len(result.text) > 80
                    else result.text,
            }},
        )

        segments = [
            TranscriptSegment(start=s.start, end=s.end, text=s.text)
            for s in result.segments
        ]
        repo.save_chunk_result(job_id, index, segments, language=result.language)
        if repo.try_claim_stitch(job_id):
            logger.info(
                "Stitch claim won — dispatching stitch",
                extra={"fields": {"job_id": job_id}},
            )
            from app.worker.tasks import stitch_results

            try:
                stitch_results.delay(job_id)
            except Exception:
                # Dispatch failed (e.g. broker down). Release the claim so that
                # the next chunk-task completion can re-win the stitch race
                # instead of leaving the job stuck in PROCESSING forever.
                repo.release_stitch_claim(job_id)
                raise
        return index
    except SoftTimeLimitExceeded:
        logger.error(
            "Chunk timed out",
            extra={"fields": {"job_id": job_id, "index": index}},
        )
        if repo.mark_failed(job_id, error=f"chunk {index}: timed out", chunk_index=index):
            JOBS_FAILED.labels(reason="timeout").inc()
            JOBS_IN_FLIGHT.dec()
        raise
    except Exception as exc:
        backoff = settings.celery_retry_backoff_base_seconds ** (task.request.retries + 1)
        if task.request.retries < settings.celery_max_retries:
            logger.warning(
                "Chunk failed, retrying",
                extra={"fields": {"job_id": job_id, "index": index, "in": backoff}},
            )
            raise task.retry(exc=exc, countdown=backoff) from exc
        if repo.mark_failed(job_id, error=f"chunk {index}: {exc}", chunk_index=index):
            JOBS_FAILED.labels(reason="chunk").inc()
            JOBS_IN_FLIGHT.dec()
        raise
    finally:
        CHUNKS_IN_PROGRESS.dec()
        window_path.unlink(missing_ok=True)
