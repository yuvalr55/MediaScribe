"""Correlation-id propagation.

A correlation id ties together every log line produced while handling a single
request — and follows the work as it crosses the queue into a Celery task — so a
job can be traced end to end. It is stored in a `ContextVar`, which is safe for
both asyncio tasks and threads.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Generate a fresh correlation id."""
    return uuid.uuid4().hex


def set_correlation_id(value: str | None) -> str:
    """Bind a correlation id to the current context, generating one if absent."""
    cid = value or new_correlation_id()
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""
    return _correlation_id.get()
