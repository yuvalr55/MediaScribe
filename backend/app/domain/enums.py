"""Job and chunk lifecycle states."""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """The lifecycle of a transcription job.

    PENDING    -> accepted, queued, not yet picked up
    PROCESSING -> a worker is splitting/transcribing
    COMPLETED  -> transcript available
    FAILED     -> gave up (with `error` populated); fail-fast on any chunk
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED)


class JobPhase(str, Enum):
    """Fine-grained phase within the PROCESSING state.

    `status` stays coarse (PENDING/PROCESSING/...); `phase` reports *what* the
    worker is doing while PROCESSING so the UI can show a real reported step
    instead of inferring one from `progress`.

    QUEUED      -> not being worked on (PENDING / between retries)
    STARTING    -> worker picked it up: probing + planning chunks
    TRANSCRIBING-> chunks dispatched, transcription in flight
    STITCHING   -> combining chunk transcripts into the final result
    """

    QUEUED = "QUEUED"
    STARTING = "STARTING"
    TRANSCRIBING = "TRANSCRIBING"
    STITCHING = "STITCHING"


class ChunkStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
