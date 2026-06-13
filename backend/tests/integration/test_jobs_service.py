"""JobsService: upload streaming, dedup, validation, retry."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.api.services.jobs_service import JobsService
from app.core.exceptions import (
    InvalidJobStateError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.domain.enums import JobStatus


async def _stream(data: bytes, block: int = 4) -> AsyncIterator[bytes]:
    for i in range(0, len(data), block):
        yield data[i : i + block]


def _service(settings, storage):
    calls: list[str] = []
    service = JobsService(settings, storage, calls.append)
    return service, calls


@pytest.mark.asyncio
async def test_create_job_persists_and_enqueues(init_db, settings, storage):
    service, calls = _service(settings, storage)

    job, deduped = await service.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"hello bytes")
    )

    assert deduped is False
    assert job.status == JobStatus.PENDING
    assert job.size_bytes == len(b"hello bytes")
    assert calls == [str(job.id)]  # enqueued exactly once


@pytest.mark.asyncio
async def test_identical_content_is_deduplicated(init_db, settings, storage):
    service, calls = _service(settings, storage)

    first, _ = await service.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"same")
    )
    second, deduped = await service.create_job(
        filename="b.wav", content_type="audio/wav", stream=_stream(b"same")
    )

    assert deduped is True
    assert second.id == first.id
    assert calls == [str(first.id)]  # not enqueued again


@pytest.mark.asyncio
async def test_unsupported_content_type_rejected(init_db, settings, storage):
    service, _ = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError):
        await service.create_job(
            filename="x.txt", content_type="text/plain", stream=_stream(b"nope")
        )


@pytest.mark.asyncio
async def test_oversized_upload_rejected(init_db, settings, storage):
    settings.max_upload_bytes = 4
    service, _ = _service(settings, storage)
    with pytest.raises(PayloadTooLargeError):
        await service.create_job(
            filename="big.wav", content_type="audio/wav", stream=_stream(b"way too big")
        )


@pytest.mark.asyncio
async def test_retry_only_allowed_from_failed(init_db, settings, storage):
    service, _ = _service(settings, storage)
    job, _ = await service.create_job(
        filename="a.wav", content_type="audio/wav", stream=_stream(b"data")
    )

    with pytest.raises(InvalidJobStateError):
        await service.retry_job(str(job.id))

    job.status = JobStatus.FAILED
    await job.save()
    retried = await service.retry_job(str(job.id))
    assert retried.status == JobStatus.PENDING
    assert retried.error is None
