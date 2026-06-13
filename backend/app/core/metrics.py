"""Prometheus metrics.

These are *business* metrics — how many jobs were created, how long transcription
takes, how much audio was processed — in addition to the HTTP metrics that the
instrumentator adds automatically. They are shared by the API and the worker so
a Grafana dashboard can show the whole pipeline.

Metrics use the multiprocess-safe default registry; in the Celery prefork pool
each child process exports its own series, scraped via a small metrics endpoint
(see ``app.worker.metrics_server``).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

JOBS_CREATED = Counter(
    "mediascribe_jobs_created_total",
    "Number of transcription jobs accepted.",
)
JOBS_COMPLETED = Counter(
    "mediascribe_jobs_completed_total",
    "Number of jobs that finished successfully.",
)
JOBS_FAILED = Counter(
    "mediascribe_jobs_failed_total",
    "Number of jobs that ended in failure.",
    ["reason"],
)
JOBS_DEDUPLICATED = Counter(
    "mediascribe_jobs_deduplicated_total",
    "Uploads short-circuited to an existing transcription by content hash.",
)

TRANSCRIPTION_DURATION = Histogram(
    "mediascribe_transcription_duration_seconds",
    "Wall-clock time to transcribe a single chunk.",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
JOB_LATENCY = Histogram(
    "mediascribe_job_latency_seconds",
    "End-to-end wall-clock time from job creation to successful completion.",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)
AUDIO_PROCESSED = Counter(
    "mediascribe_audio_processed_seconds_total",
    "Total duration of audio transcribed.",
)

CHUNKS_IN_PROGRESS = Gauge(
    "mediascribe_chunks_in_progress",
    "Chunks currently being transcribed across all workers.",
    multiprocess_mode="livesum",
)
JOBS_IN_FLIGHT = Gauge(
    "mediascribe_jobs_in_flight",
    "Jobs currently being processed by the worker (orchestration → stitch complete).",
    multiprocess_mode="livesum",
)

REAPER_RUNS = Counter(
    "mediascribe_reaper_runs_total",
    "Number of stuck-job reaper executions.",
)
REAPER_FAILED_JOBS = Counter(
    "mediascribe_reaper_failed_jobs_total",
    "Number of stale jobs failed by the stuck-job reaper.",
)
