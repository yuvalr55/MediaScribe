"""Storage abstraction.

The service stores opaque media blobs by key. The default implementation writes
to the local filesystem; a future S3 backend can implement the same Protocol
without touching any caller. Writes are *streamed* so a multi-gigabyte upload is
never held in memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """A content-addressable-ish blob store keyed by string."""

    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> int:
        """Persist a byte stream under `key`. Returns the number of bytes written."""
        ...

    def local_path(self, key: str) -> Path:
        """Return a filesystem path the worker can read.

        The worker (ffmpeg, the model) needs a real file path. For non-local
        backends this would download to a temp file first.
        """

    async def delete(self, key: str) -> None:
        """Remove the blob if it exists (idempotent)."""
