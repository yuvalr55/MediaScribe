"""Domain exceptions and FastAPI exception handlers.

The service speaks a single error shape to clients: ``{"error": {...}}``. Domain
code raises these typed exceptions; the registered handlers translate them into
consistent HTTP responses so routes never assemble error payloads by hand.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, client-facing errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class JobNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "job_not_found"


class UnsupportedMediaTypeError(AppError):
    status_code = 422  # Unprocessable Content
    code = "unsupported_media_type"


class PayloadTooLargeError(AppError):
    status_code = 413  # Content Too Large
    code = "payload_too_large"


class InvalidJobStateError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "invalid_job_state"


def _error_response(exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire domain exceptions to consistent JSON responses."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc)
