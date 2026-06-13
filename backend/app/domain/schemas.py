"""API data-transfer objects (request/response shapes).

These are deliberately separate from the persistence models: the wire contract
should be able to evolve independently of how data is stored.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.domain.enums import JobPhase, JobStatus
from app.domain.models import Job, TranscriptSegment


class JobAccepted(BaseModel):
    """Returned from POST /jobs (HTTP 202)."""

    job_id: str
    status: JobStatus
    deduplicated: bool = False


class JobStatusResponse(BaseModel):
    """Returned from GET /jobs/{id} and items in GET /jobs.

    Reports a single, uniform `progress` fraction. Chunking is an internal
    implementation detail and is deliberately *not* exposed here — chunk-level
    metrics live in Prometheus (observability), not in the user-facing contract.
    """

    job_id: str
    status: JobStatus
    phase: JobPhase
    progress: float
    original_filename: str
    duration_seconds: float | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime
    attempts: int = 0

    @classmethod
    def from_job(cls, job: Job) -> JobStatusResponse:
        return cls(
            job_id=str(job.id),
            status=job.status,
            phase=job.phase,
            progress=round(job.progress, 4),
            original_filename=job.original_filename,
            duration_seconds=job.duration_seconds,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            attempts=job.attempts,
        )


class JobProgressResponse(BaseModel):
    """Slim response for GET /jobs?active=true — only mutable fields during processing.

    Omits static fields (original_filename, created_at, duration_seconds, attempts)
    that the client already has from the initial full fetch, keeping the poll
    payload as small as possible.
    """

    job_id: str
    status: JobStatus
    phase: JobPhase
    progress: float
    started_at: datetime
    updated_at: datetime
    error: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> JobProgressResponse:
        return cls(
            job_id=str(job.id),
            status=job.status,
            phase=job.phase,
            progress=round(job.progress, 4),
            started_at=job.started_at,
            updated_at=job.updated_at,
            error=job.error,
        )


class TranscriptResponse(BaseModel):
    """Returned from GET /jobs/{id}/result."""

    job_id: str
    language: str | None
    duration_seconds: float | None
    text: str
    segments: list[TranscriptSegment]

    @classmethod
    def from_job(cls, job: Job) -> TranscriptResponse:
        return cls(
            job_id=str(job.id),
            language=job.language,
            duration_seconds=job.duration_seconds,
            text=job.transcript_text or "",
            segments=job.segments,
        )
