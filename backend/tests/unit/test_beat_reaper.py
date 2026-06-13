from types import SimpleNamespace

from app.worker.celery_app import celery_app
from app.worker.tasks import reap_stuck_jobs


def test_celery_beat_schedules_stuck_job_reaper():
    schedule = celery_app.conf.beat_schedule["reap-stuck-jobs"]

    assert schedule["task"] == "app.worker.tasks.reap_stuck_jobs"
    assert schedule["schedule"] == 60


def test_reap_stuck_jobs_uses_configured_timeout(monkeypatch):
    calls: list[int] = []
    metric_calls: list[tuple[str, int | None]] = []

    class FakeRepository:
        def __init__(self, settings):
            self.settings = settings

        def fail_stuck_jobs(self, timeout_seconds: int) -> int:
            calls.append(timeout_seconds)
            return 3

    class FakeCounter:
        def __init__(self, name: str):
            self.name = name

        def inc(self, amount: int | None = None) -> None:
            metric_calls.append((self.name, amount))

    monkeypatch.setattr(
        "app.worker.reaper.get_settings",
        lambda: SimpleNamespace(stuck_job_timeout_seconds=123),
    )
    monkeypatch.setattr("app.worker.reaper.JobRepository", FakeRepository)
    monkeypatch.setattr("app.worker.reaper.REAPER_RUNS", FakeCounter("runs"))
    monkeypatch.setattr("app.worker.reaper.REAPER_FAILED_JOBS", FakeCounter("failed"))

    assert reap_stuck_jobs.run() == 3
    assert calls == [123]
    assert metric_calls == [("runs", None), ("failed", 3)]
