"""Job orchestration — the business logic, independent of HTTP and of Celery.

Responsibilities:
* validate and stream an upload to storage while hashing it (constant memory);
* deduplicate by content hash;
* create the `Job` document and hand work off to the queue;
* expose read/retry operations used by the API.

The actual transcription happens in the worker; this service only *enqueues* it,
keeping the request fast and non-blocking.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.core.exceptions import (
    InvalidJobStateError,
    JobNotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.core.logging import get_logger
from app.core.metrics import JOBS_CREATED, JOBS_DEDUPLICATED
from app.domain.enums import JobPhase, JobStatus
from app.domain.models import Job
from app.storage.base import StorageBackend

logger = get_logger(__name__)

_MEDIA_EXTENSIONS = frozenset({
    "mp3", "wav", "m4a", "mp4", "mov", "webm", "ogg", "aac", "flac", "opus",
    "mkv", "avi", "wmv", "wma",
})

# Signature of "enqueue this job for processing". Injected so the service does
# not import Celery directly (keeps it unit-testable and decoupled).
EnqueueFn = Callable[[str], None]


class JobsService:
    def __init__(
        self,
        settings: Settings,
        storage: StorageBackend,
        enqueue: EnqueueFn,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._enqueue = enqueue

    # --- commands -------------------------------------------------------
    async def create_job(
        self,
        *,
        filename: str,
        content_type: str,
        stream: AsyncIterator[bytes],
        correlation_id: str | None = None,
    ) -> tuple[Job, bool]:
        """Validate, persist the upload, and enqueue. Returns (job, deduplicated)."""
        self._validate_content_type(content_type, filename)

        tmp_key = f"incoming/{_random_key()}"
        try:
            # Stream to a temporary key while hashing; rename to the hash afterwards.
            sha256, size = await self._stream_and_hash(tmp_key, stream)
        except Exception:
            await self._storage.delete(tmp_key)
            raise

        if existing := await Job.find_one(Job.file_hash == sha256):
            # Identical content already transcribed (or in flight): reuse it.
            await self._storage.delete(tmp_key)
            JOBS_DEDUPLICATED.inc()
            logger.info("Deduplicated upload", extra={"fields": {"hash": sha256}})
            return existing, True

        storage_key = f"media/{sha256}"
        # Promote the temp object to its content-addressed key.
        await self._promote(tmp_key, storage_key)

        job = Job(
            file_hash=sha256,
            original_filename=filename,
            content_type=content_type,
            size_bytes=size,
            storage_key=storage_key,
            correlation_id=correlation_id,
            status=JobStatus.PENDING,
        )
        # Fix #7: handle the race where two concurrent uploads of the same file
        # both pass the find_one check before either inserts.
        try:
            from pymongo.errors import DuplicateKeyError
            await job.insert()
        except DuplicateKeyError:
            await self._storage.delete(storage_key)
            existing = await Job.find_one(Job.file_hash == sha256)
            if existing is None:
                # Duplicate key was on a different index or the concurrent insert
                # was rolled back — treat as an unexpected error.
                raise RuntimeError(
                    f"DuplicateKeyError for job with hash {sha256}"
                    " but no existing job found"
                ) from None
            JOBS_DEDUPLICATED.inc()
            return existing, True
        JOBS_CREATED.inc()

        self._enqueue(str(job.id))
        logger.info("Job created", extra={"fields": {"job_id": str(job.id)}})
        return job, False

    async def retry_job(self, job_id: str) -> Job:
        """Re-enqueue a FAILED job without re-uploading (media is already in storage)."""
        job = await self.get_job(job_id)
        if job.status != JobStatus.FAILED:
            raise InvalidJobStateError(
                "Only FAILED jobs can be retried",
                details={"status": job.status.value},
            )
        now = datetime.now(UTC)
        job.status = JobStatus.PENDING
        job.phase = JobPhase.QUEUED
        job.error = None
        job.failed_chunk_index = None
        job.duration_seconds = None
        job.language = None
        job.chunks = []
        job.transcript_text = None
        job.segments = []
        job.attempts += 1
        job.updated_at = now
        job.started_at = now
        await job.save()
        await Job.get_motor_collection().update_one(
            {"_id": job.id},
            {"$unset": {"stitch_claimed": ""}},
        )
        self._enqueue(str(job.id))
        logger.info("Job re-enqueued for retry", extra={"fields": {"job_id": job_id}})
        return job

    # --- queries --------------------------------------------------------
    async def get_job(self, job_id: str) -> Job:
        job = await _find_job(job_id)
        if job is None:
            raise JobNotFoundError("Job not found", details={"job_id": job_id})
        return job

    async def delete_job(self, job_id: str) -> None:
        """Remove a job document and its media file from storage."""
        job = await self.get_job(job_id)
        if not job.status.is_terminal:
            raise InvalidJobStateError(
                "Only terminal jobs can be deleted",
                details={"status": job.status.value},
            )
        # Only delete the media file if no other job shares the same hash.
        siblings = await Job.find(
            Job.file_hash == job.file_hash,
            Job.id != job.id,
        ).count()
        if siblings == 0:
            await self._storage.delete(job.storage_key)
        await job.delete()

    async def list_jobs(self, limit: int = 50, active_only: bool = False) -> list[Job]:
        """Return the most recent jobs, newest first.

        Pass ``active_only=True`` for the polling loop — returns only PENDING /
        PROCESSING jobs so the payload stays small regardless of total job count.
        """
        active_filter = {"status": {"$in": ["PENDING", "PROCESSING"]}}
        query = Job.find(active_filter) if active_only else Job.find_all()
        return await query.sort(-Job.created_at).limit(limit).to_list()  # type: ignore[operator]

    async def get_completed_job(self, job_id: str) -> Job:
        job = await self.get_job(job_id)
        if job.status != JobStatus.COMPLETED:
            raise InvalidJobStateError(
                "Transcript not available yet",
                details={"status": job.status.value},
            )
        return job

    async def get_media_path(self, job_id: str) -> tuple[Job, Path]:
        job = await self.get_job(job_id)
        return job, self._storage.local_path(job.storage_key)

    # --- helpers --------------------------------------------------------
    def _validate_content_type(self, content_type: str, filename: str = "") -> None:
        allowed = self._settings.allowed_content_types
        if content_type in allowed:
            return
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        # Browsers sometimes send application/octet-stream for valid media files.
        # Fall back to the file extension only for that generic content type.
        if content_type == "application/octet-stream" and ext in _MEDIA_EXTENSIONS:
            return
        raise UnsupportedMediaTypeError(
            "Unsupported file type — please upload an audio or video file"
            " (MP3, WAV, M4A, MP4, MOV, WebM, OGG)",
            details={"content_type": content_type, "extension": ext or None},
        )

    async def _stream_and_hash(
        self, key: str, stream: AsyncIterator[bytes]
    ) -> tuple[str, int]:
        """Stream to storage while enforcing the size cap and hashing."""
        hasher = hashlib.sha256()
        limit = self._settings.max_upload_bytes

        async def _guarded() -> AsyncIterator[bytes]:
            total = 0
            async for block in stream:
                total += len(block)
                if total > limit:
                    raise PayloadTooLargeError(
                        "Upload exceeds maximum allowed size",
                        details={"max_bytes": limit},
                    )
                hasher.update(block)
                yield block

        size = await self._storage.save_stream(key, _guarded())
        return hasher.hexdigest(), size

    async def _promote(self, tmp_key: str, final_key: str) -> None:
        """Move the streamed temp object to its content-addressed key."""
        src = self._storage.local_path(tmp_key)
        dst = self._storage.local_path(final_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Fall back to shutil.move for cross-device renames.
        # On failure: clean up only src (not dst, which may be partial/absent).
        # If src.replace() succeeded there is nothing to clean up.
        # If shutil.move failed mid-copy, src is still intact — leave it for
        # the caller's outer handler to delete via `self._storage.delete(tmp_key)`.
        moved_with_replace = False
        try:
            src.replace(dst)
            moved_with_replace = True
        except OSError:
            pass
        if not moved_with_replace:
            import shutil
            try:
                await asyncio.to_thread(shutil.move, str(src), str(dst))
            except Exception:
                # src is still intact; do NOT unlink it here — the caller's
                # `except` block in create_job will call storage.delete(tmp_key).
                dst.unlink(missing_ok=True)  # remove any partial destination
                raise


async def _find_job(job_id: str) -> Job | None:
    from beanie import PydanticObjectId

    try:
        oid = PydanticObjectId(job_id)
    except Exception:
        return None
    return await Job.get(oid)


def _random_key() -> str:
    import uuid

    return uuid.uuid4().hex
