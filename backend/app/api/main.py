"""FastAPI application factory.

Wires together configuration, logging, MongoDB (via the lifespan), middleware,
routes, exception handlers, and the Prometheus `/metrics` endpoint.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.db.mongo import close_mongo, init_mongo
from app.api.middleware import CorrelationIdMiddleware
from app.api.routes import health, jobs
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 — FastAPI lifespan signature
    settings = get_settings()
    configure_logging()
    await init_mongo(settings)
    logger.info("API started", extra={"fields": {"env": settings.environment}})
    try:
        yield
    finally:
        await close_mongo()
        logger.info("API stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(jobs.router)

    if settings.metrics_enabled:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()
