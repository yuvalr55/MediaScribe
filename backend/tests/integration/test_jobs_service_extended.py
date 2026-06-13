"""JobsService — extended coverage for delete, list, get_completed, concurrent dedup."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.api.services.jobs_service import JobsService
from app.core.exceptions import InvalidJobStateError, JobNotFoundError
from app.domain.enums import JobStatus
from app.domain.models import TranscriptSegment


async def _stream(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _service(settings, storage):
    calls: list[str] = []
    return JobsService(settings, storage, calls.append), calls


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_not_found_raises(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    with pytest.raises(JobNotFoundError):
        await svc.get_job("000000000000000000000000")


@pytest.mark.asyncio
async def test_get_job_invalid_id_raises(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    with pytest.raises(JobNotFoundError):
        await svc.get_job("not-an-object-id")


# ---------------------------------------------------------------------------
# get_completed_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_completed_job_raises_when_pending(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    job, _ = await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"data")
    )
    with pytest.raises(InvalidJobStateError, match="not available yet"):
        await svc.get_completed_job(str(job.id))


@pytest.mark.asyncio
async def test_get_completed_job_returns_when_completed(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    job, _ = await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"done")
    )
    job.status = JobStatus.COMPLETED
    await job.save()
    result = await svc.get_completed_job(str(job.id))
    assert result.id == job.id


# ---------------------------------------------------------------------------
# delete_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_job_removes_document(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    job, _ = await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"todelete")
    )
    job.status = JobStatus.COMPLETED
    await job.save()
    await svc.delete_job(str(job.id))
    with pytest.raises(JobNotFoundError):
        await svc.get_job(str(job.id))


@pytest.mark.asyncio
async def test_delete_job_removes_storage_when_no_siblings(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    job, _ = await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"unique-content-xyz")
    )
    job.status = JobStatus.COMPLETED
    await job.save()
    storage_key = job.storage_key

    deleted_keys: list[str] = []
    original_delete = storage.delete

    async def spy_delete(key: str) -> None:
        deleted_keys.append(key)
        await original_delete(key)

    storage.delete = spy_delete
    await svc.delete_job(str(job.id))
    # No siblings → storage file must be deleted.
    assert storage_key in deleted_keys


@pytest.mark.asyncio
async def test_delete_job_rejects_active_job(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    job, _ = await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"active")
    )

    with pytest.raises(InvalidJobStateError, match="terminal"):
        await svc.delete_job(str(job.id))


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_jobs_returns_all(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"aaa")
    )
    await svc.create_job(
        filename="b.wav", content_type="audio/wav", stream=_stream(b"bbb")
    )
    jobs = await svc.list_jobs()
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_list_jobs_empty(init_db, settings, storage):
    svc, _ = _service(settings, storage)
    assert await svc.list_jobs() == []


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_resets_error_and_chunks(init_db, settings, storage):
    svc, calls = _service(settings, storage)
    job, _ = await svc.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"retry-me")
    )
    job.status = JobStatus.FAILED
    job.error = "some error"
    job.duration_seconds = 12
    job.language = "en"
    job.transcript_text = "old"
    job.segments = [TranscriptSegment(start=0, end=1, text="old")]
    await job.save()
    await job.get_motor_collection().update_one(
        {"_id": job.id}, {"$set": {"stitch_claimed": True}}
    )

    retried = await svc.retry_job(str(job.id))
    assert retried.status == JobStatus.PENDING
    assert retried.error is None
    assert retried.duration_seconds is None
    assert retried.language is None
    assert retried.transcript_text is None
    assert retried.segments == []
    assert retried.chunks == []  # Chunk list cleared
    raw = await job.get_motor_collection().find_one({"_id": job.id})
    assert "stitch_claimed" not in raw
    assert calls.count(str(job.id)) == 2  # initial enqueue + retry
