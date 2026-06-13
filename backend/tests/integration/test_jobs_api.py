"""HTTP contract tests for every job endpoint.

Drives the real FastAPI app through an in-process ASGI transport. The Celery
enqueue is replaced with a spy and the transcription is simulated by directly
advancing job state, so the full request/response surface is covered without any
broker or worker running.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.api.routes.jobs as jobs_routes
from app.api.dependencies import get_jobs_service
from app.api.main import create_app
from app.api.services.jobs_service import JobsService
from app.domain.enums import JobStatus
from app.domain.models import Job, TranscriptSegment


@pytest_asyncio.fixture
async def client(init_db, settings, storage):
    enqueued: list[str] = []
    app = create_app()
    app.dependency_overrides[get_jobs_service] = lambda: JobsService(
        settings, storage, enqueued.append
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.enqueued = enqueued  # type: ignore[attr-defined]
        yield c


def _audio():
    return {"file": ("clip.wav", b"fake audio bytes", "audio/wav")}


@pytest.mark.asyncio
async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_upload_returns_202_and_enqueues(client):
    res = await client.post("/jobs", files=_audio())
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "PENDING"
    assert client.enqueued == [body["job_id"]]


@pytest.mark.asyncio
async def test_jobs_routes_require_api_key_when_configured(monkeypatch):
    monkeypatch.setattr(
        jobs_routes,
        "get_settings",
        lambda: type("SettingsStub", (), {"api_auth_token": "secret"})(),
    )

    with pytest.raises(Exception) as exc_info:
        jobs_routes.require_api_auth(api_key_header=None, api_key=None)
    assert exc_info.value.status_code == 401

    assert jobs_routes.require_api_auth(api_key_header="secret", api_key=None) is None


@pytest.mark.asyncio
async def test_unsupported_type_returns_422(client):
    res = await client.post("/jobs", files={"file": ("a.txt", b"x", "text/plain")})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.asyncio
async def test_status_and_result_lifecycle(client):
    job_id = (await client.post("/jobs", files=_audio())).json()["job_id"]

    # Result is not available while pending -> 409.
    assert (await client.get(f"/jobs/{job_id}/result")).status_code == 409

    # Simulate the worker completing the job.
    job = await Job.get(job_id)
    job.status = JobStatus.COMPLETED
    job.transcript_text = "hello world"
    job.segments = [TranscriptSegment(start=0, end=1, text="hello world")]
    await job.save()

    status = (await client.get(f"/jobs/{job_id}")).json()
    assert status["status"] == "COMPLETED"
    assert status["progress"] == 1.0

    result = (await client.get(f"/jobs/{job_id}/result")).json()
    assert result["text"] == "hello world"
    assert len(result["segments"]) == 1


@pytest.mark.asyncio
async def test_unknown_job_returns_404(client):
    assert (await client.get("/jobs/000000000000000000000000")).status_code == 404


@pytest.mark.asyncio
async def test_retry_failed_job(client):
    job_id = (await client.post("/jobs", files=_audio())).json()["job_id"]
    job = await Job.get(job_id)
    job.status = JobStatus.FAILED
    job.error = "boom"
    await job.save()

    res = await client.post(f"/jobs/{job_id}/retry")
    assert res.status_code == 202
    assert res.json()["status"] == "PENDING"
    assert client.enqueued[-1] == job_id  # re-enqueued
