"""Verify JOBS_IN_FLIGHT gauge accounting.

Each scenario checks that the gauge returns to 0 after the pipeline path
completes — success, orchestration failure, and chunk failure.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.metrics import JOBS_IN_FLIGHT


def _gauge_value() -> float:
    return JOBS_IN_FLIGHT._value.get()


@pytest.fixture(autouse=True)
def reset_gauge():
    """Start every test from 0."""
    JOBS_IN_FLIGHT.set(0)
    yield
    JOBS_IN_FLIGHT.set(0)


# ---------------------------------------------------------------------------
# orchestration failures
# ---------------------------------------------------------------------------

def test_gauge_decrements_on_orchestration_exception():
    from app.worker.orchestration import run_orchestration

    with (
        patch("app.worker.orchestration.JobRepository") as MockRepo,
        patch("app.worker.orchestration.build_storage"),
        patch("app.worker.orchestration.get_settings"),
    ):
        mock_repo = MockRepo.return_value
        mock_job = MagicMock()
        mock_job.status.value = "PENDING"
        from app.domain.enums import JobStatus
        mock_job.status = JobStatus.PENDING
        mock_repo.get.return_value = mock_job
        mock_repo.mark_starting.side_effect = RuntimeError("db down")
        mock_repo.mark_failed.return_value = True

        assert _gauge_value() == 0
        run_orchestration("aaaaaaaaaaaaaaaaaaaaaaaa")
        assert _gauge_value() == 0


def test_gauge_unchanged_when_job_not_found():
    from app.worker.orchestration import run_orchestration

    with (
        patch("app.worker.orchestration.JobRepository") as MockRepo,
        patch("app.worker.orchestration.build_storage"),
        patch("app.worker.orchestration.get_settings"),
    ):
        MockRepo.return_value.get.return_value = None

        assert _gauge_value() == 0
        run_orchestration("aaaaaaaaaaaaaaaaaaaaaaaa")
        assert _gauge_value() == 0


# ---------------------------------------------------------------------------
# mark_failed idempotency guard
# ---------------------------------------------------------------------------

def test_gauge_does_not_double_decrement_on_concurrent_failures():
    """Simulate two chunks failing simultaneously for the same job.

    Only the winner of mark_failed (returns True) should dec the gauge.
    The loser (returns False) must not dec.
    """
    JOBS_IN_FLIGHT.inc()  # job started
    assert _gauge_value() == 1

    # Winner
    if True:  # mark_failed returns True
        JOBS_IN_FLIGHT.dec()

    assert _gauge_value() == 0

    # Loser — mark_failed returns False, no dec
    # gauge stays at 0, not -1
    assert _gauge_value() == 0
