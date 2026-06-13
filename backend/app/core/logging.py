"""Structured logging configuration.

Logs are emitted as single-line JSON (in production) so they can be ingested by
a log aggregator, with the active correlation id attached to every record. Set
`LOG_JSON=false` for human-friendly output during local development.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.core.correlation import get_correlation_id


class _JsonFormatter(logging.Formatter):
    """Render log records as compact JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if cid := get_correlation_id():
            payload["correlation_id"] = cid
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Allow callers to attach structured fields via `extra={"fields": {...}}`.
        if extra := getattr(record, "fields", None):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _CorrelationFilter(logging.Filter):
    """Inject the correlation id so plain-text formatters can reference it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


def configure_logging() -> None:
    """Configure the root logger once, based on settings. Idempotent."""
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_CorrelationFilter())
    if settings.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s [%(correlation_id)s] "
                "%(name)s: %(message)s"
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
