"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.models import Job

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe (checks MongoDB)")
async def ready() -> dict[str, str]:
    # A cheap query confirms the database connection is usable.
    await Job.find_all().limit(1).to_list()
    return {"status": "ready"}
