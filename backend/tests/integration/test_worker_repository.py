"""Worker-side persistence and the stitch coordination claim.

The worker uses synchronous pymongo, which ``mongomock`` emulates faithfully, so
these run with no real MongoDB. We patch the module-level client and exercise the
state transitions plus the atomic ``try_claim_stitch`` that replaces a Celery
chord as the "all chunks done" synchronization point.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import mongomock
import pytest
from bson import ObjectId

import app.worker.repository as repo_module
from app.domain.enums import ChunkStatus, JobStatus
from app.domain.models import TranscriptSegment


@pytest.fixture
def repo(settings, monkeypatch):
    """A JobRepository backed by an in-memory mongomock client."""
    client = mongomock.MongoClient()
    monkeypatch.setattr(repo_module, "_client", client)
    return repo_module.JobRepository(settings)


def _insert(repo, **overrides) -> str:
    doc = {
        "status": JobStatus.PROCESSING.value,
        "updated_at": datetime.now(UTC),
        **overrides,
    }
    return str(repo._col.insert_one(doc).inserted_id)


def test_mark_completed_persists_transcript(repo):
    job_id = _insert(repo)
    completed = repo.mark_completed(
        job_id,
        text="hello world",
        segments=[TranscriptSegment(start=0, end=1, text="hello world")],
        language="en",
    )
    doc = repo._col.find_one({"_id": ObjectId(job_id)})
    assert completed is True
    assert doc["status"] == JobStatus.COMPLETED.value
    assert doc["transcript_text"] == "hello world"
    assert doc["language"] == "en"


def test_mark_completed_does_not_resurrect_failed_job(repo):
    job_id = _insert(repo, status=JobStatus.FAILED.value, error="stale")

    completed = repo.mark_completed(
        job_id,
        text="late transcript",
        segments=[TranscriptSegment(start=0, end=1, text="late transcript")],
        language="en",
    )

    doc = repo._col.find_one({"_id": ObjectId(job_id)})
    assert completed is False
    assert doc["status"] == JobStatus.FAILED.value
    assert doc["error"] == "stale"
    assert "transcript_text" not in doc


def test_mark_failed_records_reason_and_chunk(repo):
    job_id = _insert(repo)
    result = repo.mark_failed(job_id, error="chunk 2: boom", chunk_index=2)
    doc = repo._col.find_one({"_id": ObjectId(job_id)})
    assert result is True
    assert doc["status"] == JobStatus.FAILED.value
    assert doc["error"] == "chunk 2: boom"
    assert doc["failed_chunk_index"] == 2


def test_mark_failed_idempotent_returns_false_on_second_call(repo):
    job_id = _insert(repo)
    first = repo.mark_failed(job_id, error="first failure")
    second = repo.mark_failed(job_id, error="second failure")
    doc = repo._col.find_one({"_id": ObjectId(job_id)})
    assert first is True
    assert second is False
    assert doc["error"] == "first failure"


def test_heartbeat_advances_updated_at(repo):
    # pymongo (and mongomock) return tz-naive datetimes on read, so compare naive.
    old = datetime(2000, 1, 1)
    job_id = _insert(repo, updated_at=old)
    repo.heartbeat(job_id)
    doc = repo._col.find_one({"_id": ObjectId(job_id)})
    assert doc["updated_at"].replace(tzinfo=None) > old


def test_fail_stuck_jobs_marks_old_processing_jobs_failed(repo):
    old = datetime.now(UTC) - timedelta(seconds=601)
    fresh = datetime.now(UTC)
    stuck_id = _insert(repo, updated_at=old)
    fresh_id = _insert(repo, updated_at=fresh)

    assert repo.fail_stuck_jobs(timeout_seconds=600) == 1

    stuck = repo._col.find_one({"_id": ObjectId(stuck_id)})
    fresh_doc = repo._col.find_one({"_id": ObjectId(fresh_id)})
    assert stuck["status"] == JobStatus.FAILED.value
    assert stuck["error"] == "job stale for more than 600s"
    assert fresh_doc["status"] == JobStatus.PROCESSING.value


def _chunks(*statuses: ChunkStatus) -> list[dict]:
    return [
        {"index": i, "start_seconds": 0.0, "end_seconds": 1.0, "status": s.value}
        for i, s in enumerate(statuses)
    ]


def test_claim_stitch_succeeds_only_when_all_chunks_completed(repo):
    job_id = _insert(
        repo, chunks=_chunks(ChunkStatus.COMPLETED, ChunkStatus.PENDING)
    )
    # One chunk still pending => no claim.
    assert repo.try_claim_stitch(job_id) is False

    repo.save_chunk_result(job_id, 1, [])
    # All chunks completed => exactly one claim succeeds...
    assert repo.try_claim_stitch(job_id) is True
    # ...and a second attempt is rejected (idempotent dispatch).
    assert repo.try_claim_stitch(job_id) is False
