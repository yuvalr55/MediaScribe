"""HTTP middleware: correlation id per request.

Reads an inbound `X-Correlation-ID` (or generates one), binds it for the lifetime
of the request so every log line carries it, and echoes it back on the response.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.correlation import set_correlation_id

HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        cid = set_correlation_id(request.headers.get(HEADER))
        response = await call_next(request)
        response.headers[HEADER] = cid
        return response
