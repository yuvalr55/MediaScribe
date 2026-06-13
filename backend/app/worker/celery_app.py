"""Celery application."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready
from kombu import Queue

from app.config import get_settings

settings = get_settings()

celery_app = Celery("mediascribe", broker=settings.rabbitmq_url)

_main_queue = Queue(settings.celery_task_queue)

celery_app.conf.update(
    task_default_queue=settings.celery_task_queue,
    task_queues=[_main_queue],
    task_routes={
        "app.worker.tasks.*": {"queue": settings.celery_task_queue},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair dispatch for long tasks
    worker_send_task_events=False,  # no Flower/monitoring — skip celeryev queue
    task_send_sent_event=False,
    worker_concurrency=settings.celery_concurrency,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "reap-stuck-jobs": {
            "task": "app.worker.tasks.reap_stuck_jobs",
            "schedule": settings.stuck_job_reaper_interval_seconds,
            # Discard missed runs — prevents burst on worker restart
            "options": {"expires": settings.stuck_job_reaper_interval_seconds},
        },
    },
)

# Ensure task modules are imported so they register with the app.
celery_app.autodiscover_tasks(["app.worker.tasks"], related_name=None)


@worker_ready.connect
def _start_worker_metrics(**_kwargs):
    """Start the multiprocess metrics HTTP server once the worker boots."""
    from app.worker.metrics_server import start_metrics_server
    start_metrics_server()
