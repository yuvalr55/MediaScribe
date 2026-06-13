"""Persistence models (MongoDB documents via Beanie).

`Job` is the single source of truth for a transcription's state. It embeds the
list of `Chunk`s — MongoDB's document model is a natural fit here, since a job
and its chunks are always read and written together.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pymongo
from beanie import Document
from pydantic import BaseModel, Field

from app.domain.enums import ChunkStatus, JobPhase, JobStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TranscriptSegment(BaseModel):
    """A timestamped span of recognised speech (global timeline)."""

    start: float
    end: float
    text: str


class Chunk(BaseModel):
    """One slice of audio, transcribed independently and then stitched back."""

    index: int
    start_seconds: float
    end_seconds: float
    status: ChunkStatus = ChunkStatus.PENDING
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str | None = None
    error: str | None = None


class JobBase(BaseModel):
    """Fields shared between the Beanie API document and the pymongo worker read-model.

    Two runtimes touch one MongoDB collection: the async API (Motor/Beanie) and
    the synchronous Celery worker (pymongo). Both need a typed view of the same
    document shape, so the shared fields live here once and each driver subclasses.
    """

    file_hash: str
    original_filename: str
    storage_key: str
    status: JobStatus = JobStatus.PENDING
    phase: JobPhase = JobPhase.QUEUED
    duration_seconds: float | None = None
    language: str | None = None
    chunks: list[Chunk] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class JobRecord(JobBase):
    """Synchronous worker read-model (pymongo).

    Instantiated by `JobRepository.get()` after a raw pymongo find. Must not
    inherit from Beanie `Document` — that requires `init_beanie` which only runs
    in the async API process.
    """


class Job(JobBase, Document):
    """Beanie document — the async API's read/write model."""

    # Identity / dedup (API-only fields not needed by the worker)
    content_type: str
    size_bytes: int

    # Lifecycle
    error: str | None = None
    failed_chunk_index: int | None = None

    # Result
    transcript_text: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)

    # Bookkeeping
    correlation_id: str | None = None
    attempts: int = 0  # number of manual retries (0 = first run, 1 = retried once, …)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "jobs"
        indexes = [
            pymongo.IndexModel([("file_hash", pymongo.ASCENDING)], unique=True),
            pymongo.IndexModel(
                [("status", pymongo.ASCENDING), ("updated_at", pymongo.ASCENDING)]
            ),
        ]

    # --- progress -------------------------------------------------------
    @property
    def progress(self) -> float:
        """Fraction of chunks completed, in [0, 1]."""
        if not self.chunks:
            return 1.0 if self.status == JobStatus.COMPLETED else 0.0
        done = sum(1 for c in self.chunks if c.status == ChunkStatus.COMPLETED)
        return done / len(self.chunks)
