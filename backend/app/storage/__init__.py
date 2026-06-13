"""Storage backend factory."""

from __future__ import annotations

from app.config import Settings
from app.storage.base import StorageBackend
from app.storage.local import LocalStorage


def build_storage(settings: Settings) -> StorageBackend:
    """Construct the configured storage backend."""
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_local_path)
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend!r}")
