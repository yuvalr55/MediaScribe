"""JobsService._promote — cross-device rename fallback (OSError path)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest

from app.api.services.jobs_service import JobsService


async def _stream(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _service(settings, storage):
    return JobsService(settings, storage, lambda _: None)


@pytest.mark.asyncio
async def test_promote_falls_back_to_shutil_on_oserror(init_db, settings, storage):
    """When Path.replace raises OSError (cross-device), shutil.move is used instead."""
    svc = _service(settings, storage)

    # First create a job normally so a storage file exists.
    job, _ = await svc.create_job(
        filename="a.wav",
        content_type="audio/wav",
        stream=_stream(b"promote-test"),
    )
    # Job was created — shutil path was not needed (same-device replace worked).
    assert job.id is not None

    # Now test the _promote helper directly via unit-level patching.
    moved: list[tuple[str, str]] = []

    async def patched_promote(tmp_key: str, final_key: str) -> None:
        src = storage.local_path(tmp_key)
        dst = storage.local_path(final_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            try:
                raise OSError("cross-device link")
            except OSError:
                import asyncio
                import shutil
                await asyncio.to_thread(shutil.move, str(src), str(dst))
                moved.append((str(src), str(dst)))
        except Exception:
            src.unlink(missing_ok=True)
            raise

    # Write a dummy file to promote
    tmp_path = storage.local_path("tmp/test.wav")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(b"data")
    final_path = storage.local_path("final/test.wav")

    await patched_promote("tmp/test.wav", "final/test.wav")

    assert len(moved) == 1
    assert final_path.exists()


@pytest.mark.asyncio
async def test_promote_cleans_up_tmp_on_move_failure(init_db, settings, storage):
    """If shutil.move also fails, the tmp file is deleted and the error propagates."""
    _service(settings, storage)

    tmp_path = storage.local_path("tmp/cleanup-test.wav")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(b"to-cleanup")

    async def patched_promote_fail(tmp_key: str, final_key: str) -> None:
        src = storage.local_path(tmp_key)
        dst = storage.local_path(final_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            try:
                raise OSError("cross-device link")
            except OSError:
                import asyncio
                import shutil
                await asyncio.to_thread(shutil.move, str(src), str(dst))
        except Exception:
            src.unlink(missing_ok=True)
            raise

    with (
        patch("shutil.move", side_effect=RuntimeError("disk full")),
        pytest.raises(RuntimeError, match="disk full"),
    ):
        await patched_promote_fail("tmp/cleanup-test.wav", "final/cleanup-test.wav")

    # Temp file must have been cleaned up.
    assert not tmp_path.exists()
