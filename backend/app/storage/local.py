"""Filesystem-backed storage.

Streams uploads to disk in bounded chunks. In a real deployment the
``storage_local_path`` would be a shared volume (so the API and worker see the
same files); for this assignment that is exactly what the Docker volume gives us.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from app.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def local_path(self, key: str) -> Path:
        path = self._root / key
        root = self._root.resolve()
        resolved = path.resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Storage key escapes root: {key!r}")
        return path

    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> int:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        # Open/write off the event loop to avoid blocking on disk I/O.
        handle = await asyncio.to_thread(open, path, "wb")
        try:
            async for block in stream:
                await asyncio.to_thread(handle.write, block)
                written += len(block)
        finally:
            await asyncio.to_thread(handle.close)
        return written

    async def delete(self, key: str) -> None:
        path = self.local_path(key)
        await asyncio.to_thread(path.unlink, True)  # missing_ok=True
