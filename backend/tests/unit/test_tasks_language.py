from app.domain.models import Chunk
from app.worker.tasks import _select_job_language


def test_select_job_language_uses_first_detected_language_by_chunk_order():
    chunks = [
        Chunk(index=1, start_seconds=10.0, end_seconds=20.0, language="en"),
        Chunk(index=0, start_seconds=0.0, end_seconds=10.0, language="he"),
    ]

    assert _select_job_language(chunks, default_language=None) == "he"


def test_select_job_language_falls_back_to_configured_default():
    chunks = [Chunk(index=0, start_seconds=0.0, end_seconds=10.0)]

    assert _select_job_language(chunks, default_language="he") == "he"
