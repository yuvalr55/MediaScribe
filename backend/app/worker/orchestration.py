"""Job orchestration logic for the Celery transcription pipeline."""

from __future__ import annotations

from pathlib import Path

from celery import group
from celery.exceptions import SoftTimeLimitExceeded

from app.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import AUDIO_PROCESSED, JOBS_FAILED, JOBS_IN_FLIGHT
from app.domain.enums import JobStatus
from app.domain.models import Chunk
from app.storage import build_storage
from app.worker.repository import JobRepository
from app.worker.services.media.chunker import ChunkSpec, FixedWindowChunker, VadChunker
from app.worker.services.media.ffmpeg import detect_silence_points, probe_duration_seconds

logger = get_logger(__name__)


def run_orchestration(job_id: str) -> None:
    """Probe the media, plan chunks, and dispatch the transcription fan-out."""
    settings = get_settings()
    repo = JobRepository(settings)
    storage = build_storage(settings)

    try:
        job = repo.get(job_id)
        if job is None:
            logger.error(
                "Job vanished before orchestration",
                extra={"fields": {"job_id": job_id}},
            )
            return

        if job.status != JobStatus.PENDING:
            logger.warning(
                "orchestrate_job skipped — job is not PENDING",
                extra={"fields": {"job_id": job_id, "status": job.status}},
            )
            return

        JOBS_IN_FLIGHT.inc()
        repo.mark_starting(job_id)
        logger.info(
            "Orchestration started",
            extra={"fields": {
                "job_id": job_id,
                "file": job.original_filename,
                "storage_key": job.storage_key,
            }},
        )
        source = storage.local_path(job.storage_key)
        repo.mark_transcribing(job_id)
        duration = probe_duration_seconds(source)
        logger.info(
            "Media probed",
            extra={"fields": {"job_id": job_id, "duration_s": round(duration, 2)}},
        )

        specs = _plan_chunks(job_id, source, duration)
        logger.info(
            "Chunk plan ready",
            extra={"fields": {
                "job_id": job_id,
                "chunks": len(specs),
                "windows": [f"{s.start_seconds:.1f}-{s.end_seconds:.1f}s" for s in specs],
            }},
        )

        chunk_models = [
            Chunk(index=s.index, start_seconds=s.start_seconds, end_seconds=s.end_seconds)
            for s in specs
        ]
        repo.mark_processing(job_id, duration=duration, chunks=chunk_models)
        AUDIO_PROCESSED.inc(duration)

        from app.worker.tasks import transcribe_chunk

        group(
            transcribe_chunk.s(
                job_id, spec.index, spec.start_seconds, spec.end_seconds, job.storage_key
            )
            for spec in specs
        ).apply_async()
        logger.info(
            "Chunk tasks dispatched",
            extra={"fields": {"job_id": job_id, "chunks": len(specs)}},
        )
    except SoftTimeLimitExceeded:
        logger.error("Orchestration timed out", extra={"fields": {"job_id": job_id}})
        if repo.mark_failed(job_id, error="orchestration timed out"):
            JOBS_FAILED.labels(reason="timeout").inc()
            JOBS_IN_FLIGHT.dec()
    except Exception as exc:
        logger.exception("Orchestration failed", extra={"fields": {"job_id": job_id}})
        if repo.mark_failed(job_id, error=f"orchestration: {exc}"):
            JOBS_FAILED.labels(reason="orchestration").inc()
            JOBS_IN_FLIGHT.dec()


def _plan_chunks(job_id: str, source: Path, duration: float) -> list[ChunkSpec]:
    settings = get_settings()
    if duration <= settings.chunk_threshold_seconds:
        logger.info(
            "Chunking strategy: single chunk (below threshold)",
            extra={"fields": {
                "job_id": job_id,
                "threshold_s": settings.chunk_threshold_seconds,
            }},
        )
        return [ChunkSpec(index=0, start_seconds=0.0, end_seconds=duration)]

    silence_points = detect_silence_points(source)
    chunker: VadChunker | FixedWindowChunker
    if silence_points:
        chunker = VadChunker(settings.chunk_length_seconds, silence_points)
        logger.info(
            "Chunking strategy: VAD",
            extra={"fields": {
                "job_id": job_id,
                "silence_points": len(silence_points),
                "points": [round(point, 2) for point in silence_points],
            }},
        )
    else:
        chunker = FixedWindowChunker(
            settings.chunk_length_seconds, settings.chunk_overlap_seconds
        )
        logger.warning(
            "Chunking strategy: fixed window (no silence found"
            " — sentences may split at boundaries)",
            extra={"fields": {
                "job_id": job_id,
                "window_s": settings.chunk_length_seconds,
                "overlap_s": settings.chunk_overlap_seconds,
            }},
        )
    return chunker.plan(duration)
