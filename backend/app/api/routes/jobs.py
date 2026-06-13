"""Job endpoints.

    GET    /jobs              list recent jobs (newest first)
    POST   /jobs              upload media, returns 202 + job id
    GET    /jobs/{id}         poll status + progress
    GET    /jobs/{id}/audio   stream the original media file
    GET    /jobs/{id}/result  fetch the transcript (once COMPLETED)
    POST   /jobs/{id}/retry   re-run a FAILED job without re-uploading
    DELETE /jobs/{id}         remove job and its media from storage
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader

from app.api.dependencies import get_jobs_service
from app.api.services.jobs_service import JobsService
from app.config import get_settings
from app.core.correlation import get_correlation_id
from app.core.logging import get_logger
from app.domain.schemas import (
    JobAccepted,
    JobProgressResponse,
    JobStatusResponse,
    TranscriptResponse,
)

_STORAGE_KEY_RE = re.compile(r"^media/[0-9a-f]{64}$")

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = get_logger(__name__)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_auth(
    api_key_header: str | None = Depends(_api_key_header),
    api_key: str | None = Query(default=None),
) -> None:
    token = get_settings().api_auth_token
    if token and api_key_header != token and api_key != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


@router.get(
    "",
    response_model=list[JobProgressResponse] | list[JobStatusResponse],
    summary="List recent jobs",
)
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    active_only: bool = Query(default=False, alias="active"),
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> list[JobProgressResponse] | list[JobStatusResponse]:
    jobs = await service.list_jobs(limit=limit, active_only=active_only)
    if active_only:
        return [JobProgressResponse.from_job(j) for j in jobs]
    return [JobStatusResponse.from_job(j) for j in jobs]


async def _iter_upload(upload: UploadFile) -> AsyncIterator[bytes]:
    """Yield the upload in bounded blocks so large files never sit in memory."""
    chunk_size = get_settings().upload_chunk_bytes
    while block := await upload.read(chunk_size):
        yield block


@router.post(
    "",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a media file for transcription",
)
async def create_job(
    file: UploadFile = File(...),
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> JobAccepted:
    logger.info(
        "Upload received",
        extra={"fields": {"filename": file.filename, "content_type": file.content_type}},
    )
    job, deduplicated = await service.create_job(
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        stream=_iter_upload(file),
        correlation_id=get_correlation_id(),
    )
    if deduplicated:
        logger.info(
            "Upload deduplicated — returning existing job",
            extra={"fields": {"job_id": str(job.id), "filename": file.filename}},
        )
    else:
        logger.info(
            "Job accepted",
            extra={"fields": {"job_id": str(job.id), "filename": file.filename}},
        )
    return JobAccepted(
        job_id=str(job.id), status=job.status, deduplicated=deduplicated
    )


@router.get("/{job_id}", response_model=JobStatusResponse, summary="Get job status")
async def get_job(
    job_id: str,
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> JobStatusResponse:
    job = await service.get_job(job_id)
    return JobStatusResponse.from_job(job)


@router.get(
    "/{job_id}/result",
    response_model=TranscriptResponse,
    summary="Get the transcript (HTTP 409 until COMPLETED)",
)
async def get_result(
    job_id: str,
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> TranscriptResponse:
    job = await service.get_completed_job(job_id)
    logger.info(
        "Transcript fetched",
        extra={"fields": {"job_id": job_id, "segments": len(job.segments)}},
    )
    return TranscriptResponse.from_job(job)


@router.get("/{job_id}/audio", summary="Stream the original media file")
async def get_audio(
    job_id: str,
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> FileResponse:
    job, path = await service.get_media_path(job_id)
    if not _STORAGE_KEY_RE.match(job.storage_key):
        raise HTTPException(status_code=500, detail="Invalid storage key")
    logger.debug(
        "Audio stream requested",
        extra={"fields": {"job_id": job_id, "filename": job.original_filename}},
    )
    return FileResponse(
        path=str(path),
        media_type=job.content_type,
        filename=job.original_filename,
    )


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a job and its media",
)
async def delete_job(
    job_id: str,
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> None:
    await service.delete_job(job_id)
    logger.info("Job deleted", extra={"fields": {"job_id": job_id}})


@router.post(
    "/{job_id}/retry",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a FAILED job",
)
async def retry_job(
    job_id: str,
    _: None = Depends(require_api_auth),
    service: JobsService = Depends(get_jobs_service),
) -> JobAccepted:
    logger.info("Job retry requested", extra={"fields": {"job_id": job_id}})
    job = await service.retry_job(job_id)
    return JobAccepted(job_id=str(job.id), status=job.status)
