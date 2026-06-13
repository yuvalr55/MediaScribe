"""Expose worker metrics over HTTP for Prometheus to scrape.

The Celery prefork pool runs several child *processes*, so we use
``prometheus_client``'s multiprocess mode: each child writes metric samples to a
shared directory (``PROMETHEUS_MULTIPROC_DIR``) and the parent process serves an
aggregated ``/`` endpoint on port 9100.

Wired via Celery's ``worker_process_init`` / ``worker_ready`` signals in
``celery_app`` so it starts automatically with the worker.
"""

from __future__ import annotations

import os
from wsgiref.simple_server import make_server

from prometheus_client import CollectorRegistry, make_wsgi_app, multiprocess

from app.core.logging import get_logger

logger = get_logger(__name__)
METRICS_PORT = 9100


def start_metrics_server() -> None:
    """Serve aggregated multiprocess metrics (called once in the worker parent)."""
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        logger.info("PROMETHEUS_MULTIPROC_DIR unset; worker metrics disabled")
        return

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    app = make_wsgi_app(registry)

    import threading

    def _serve() -> None:
        httpd = make_server("0.0.0.0", METRICS_PORT, app)
        httpd.serve_forever()

    threading.Thread(target=_serve, daemon=True).start()
    logger.info("Worker metrics server started", extra={"fields": {"port": METRICS_PORT}})
