"""Synchronous job repository for the worker.

Celery tasks are synchronous, so the worker talks to MongoDB through pymongo
rather than Motor. This module isolates all of that access behind small,
intention-revealing methods, and converts between raw documents and the domain
models so task code stays clean.

State transitions also refresh `updated_at`, which doubles as the heartbeat the
stuck-job reaper relies on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection

from app.config import Settings
from app.core.logging import get_logger
from app.core.metrics import JOBS_IN_FLIGHT
from app.domain.enums import ChunkStatus, JobPhase, JobStatus
from app.domain.models import Chunk, JobRecord, TranscriptSegment

_client: MongoClient | None = None
logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobRepository:
    def __init__(self, settings: Settings) -> None:
        global _client
        if _client is None:
            _client = MongoClient(settings.mongo_uri)
        self._col: Collection = _client[settings.mongo_database]["jobs"]

    # --- read -----------------------------------------------------------
    def get(self, job_id: str) -> JobRecord | None:
        doc = self._col.find_one({"_id": ObjectId(job_id)})
        return JobRecord.model_validate(doc) if doc else None

    # --- write ----------------------------------------------------------
    def mark_processing(
        self, job_id: str, *, duration: float, chunks: list[Chunk]
    ) -> None:
        self._col.update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "status": JobStatus.PROCESSING.value,
                    "phase": JobPhase.TRANSCRIBING.value,
                    "duration_seconds": duration,
                    "chunks": [c.model_dump() for c in chunks],
                    "updated_at": _utcnow(),
                },
            },
        )
        logger.info(
            "Job → PROCESSING",
            extra={"fields": {
                "job_id": job_id,
                "duration_s": round(duration, 2),
                "chunks": len(chunks),
            }},
        )

    def save_chunk_result(
        self,
        job_id: str,
        index: int,
        segments: list[TranscriptSegment],
        language: str | None = None,
    ) -> None:
        self._col.update_one(
            {
                "_id": ObjectId(job_id),
                "chunks.index": index,
                "status": {"$ne": JobStatus.FAILED.value},
            },
            {
                "$set": {
                    "chunks.$.status": ChunkStatus.COMPLETED.value,
                    "chunks.$.segments": [s.model_dump() for s in segments],
                    "chunks.$.language": language,
                    "updated_at": _utcnow(),
                }
            },
        )
        logger.info(
            "Chunk result saved",
            extra={"fields": {
                "job_id": job_id,
                "chunk": index,
                "segs": len(segments),
                "language": language,
            }},
        )

    def mark_completed(
        self,
        job_id: str,
        *,
        text: str,
        segments: list[TranscriptSegment],
        language: str | None,
    ) -> bool:
        result = self._col.update_one(
            {"_id": ObjectId(job_id), "status": {"$ne": JobStatus.FAILED.value}},
            {
                "$set": {
                    "status": JobStatus.COMPLETED.value,
                    "transcript_text": text,
                    "segments": [s.model_dump() for s in segments],
                    "language": language,
                    "updated_at": _utcnow(),
                }
            },
        )
        if result.modified_count == 0:
            logger.warning(
                "Job completion skipped",
                extra={"fields": {"job_id": job_id, "reason": "already failed"}},
            )
            return False
        logger.info(
            "Job → COMPLETED",
            extra={"fields": {
                "job_id": job_id,
                "segments": len(segments),
                "words": len(text.split()),
                "language": language,
            }},
        )
        return True

    def mark_failed(
        self, job_id: str, *, error: str, chunk_index: int | None = None
    ) -> bool:
        """Transition job to FAILED. Returns True only for the first caller."""
        result = self._col.update_one(
            {"_id": ObjectId(job_id), "status": {"$ne": JobStatus.FAILED.value}},
            {
                "$set": {
                    "status": JobStatus.FAILED.value,
                    "error": error,
                    "failed_chunk_index": chunk_index,
                    "updated_at": _utcnow(),
                }
            },
        )
        if result.matched_count:
            logger.error(
                "Job → FAILED",
                extra={"fields": {
                    "job_id": job_id, "chunk": chunk_index, "error": error
                }},
            )
        return bool(result.matched_count)

    def mark_starting(self, job_id: str) -> None:
        """Worker picked up the job — advance status so UI shows 'Starting'."""
        self._col.update_one(
            {"_id": ObjectId(job_id), "status": JobStatus.PENDING.value},
            {"$set": {
                "status": JobStatus.PROCESSING.value,
                "phase": JobPhase.STARTING.value,
                "updated_at": _utcnow(),
            }},
        )

    def mark_transcribing(self, job_id: str) -> None:
        """Past 'entered the worker' — now validating + transcribing the media.

        Advancing the phase here (before the probe) means 'Starting' is shown as
        completed and any validation/processing failure lands on 'Transcribing',
        not on 'Starting' (which only represents the worker pickup).
        """
        self._col.update_one(
            {"_id": ObjectId(job_id), "status": {"$ne": JobStatus.FAILED.value}},
            {"$set": {"phase": JobPhase.TRANSCRIBING.value, "updated_at": _utcnow()}},
        )

    def mark_stitching(self, job_id: str) -> None:
        """All chunks done — combining results into the final transcript."""
        self._col.update_one(
            {"_id": ObjectId(job_id), "status": {"$ne": JobStatus.FAILED.value}},
            {"$set": {"phase": JobPhase.STITCHING.value, "updated_at": _utcnow()}},
        )

    def heartbeat(self, job_id: str) -> None:
        self._col.update_one(
            {"_id": ObjectId(job_id)}, {"$set": {"updated_at": _utcnow()}}
        )

    def fail_stuck_jobs(self, timeout_seconds: int) -> int:
        cutoff = _utcnow() - timedelta(seconds=timeout_seconds)
        now = _utcnow()
        result = self._col.update_many(
            {
                "status": JobStatus.PROCESSING.value,
                "updated_at": {"$lt": cutoff},
            },
            {
                "$set": {
                    "status": JobStatus.FAILED.value,
                    "error": f"job stale for more than {timeout_seconds}s",
                    "updated_at": now,
                }
            },
        )
        failed = result.modified_count
        if failed:
            logger.warning(
                "Stuck jobs failed",
                extra={"fields": {"count": failed, "timeout_s": timeout_seconds}},
            )
            JOBS_IN_FLIGHT.dec(failed)
        return failed

    def try_claim_stitch(self, job_id: str) -> bool:  # noqa: D401
        """Atomically decide whether *this* caller should run the stitch step.

        Replaces a Celery chord (which would require a result backend) with a
        race-free coordination point in MongoDB: the update matches only when
        every chunk is COMPLETED and the stitch has not yet been claimed, then
        sets the claim flag. Exactly one concurrent worker wins.
        """
        claimed = self._col.find_one_and_update(
            {
                "_id": ObjectId(job_id),
                # don't stitch a failed job
                "status": {"$ne": JobStatus.FAILED.value},
                "stitch_claimed": {"$ne": True},
                # at least one chunk must exist
                "chunks.0": {"$exists": True},
                # No chunk is in a non-completed state => all are done.
                "chunks": {
                    "$not": {
                        "$elemMatch": {"status": {"$ne": ChunkStatus.COMPLETED.value}}
                    }
                },
            },
            {"$set": {"stitch_claimed": True}},
        )
        won = claimed is not None
        logger.debug(
            "Stitch claim %s",
            "won" if won else "lost (another worker will stitch)",
            extra={"fields": {"job_id": job_id, "claimed": won}},
        )
        return won

    def release_stitch_claim(self, job_id: str) -> None:
        """Release a stitch claim so another worker (or retry) can re-dispatch it.

        Called when the dispatch of stitch_results.delay() fails after the claim
        was already set, preventing the job from getting stuck in PROCESSING
        permanently with stitch_claimed=True and no worker to finish it.
        """
        self._col.update_one(
            {"_id": ObjectId(job_id)},
            {"$unset": {"stitch_claimed": ""}},
        )
        logger.warning(
            "Stitch claim released — dispatch failed,"
            " will retry on next chunk completion",
            extra={"fields": {"job_id": job_id}},
        )
