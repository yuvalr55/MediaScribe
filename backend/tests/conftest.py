"""Shared test fixtures.

The suite runs with no external services: MongoDB is replaced by
``mongomock_motor`` and transcription by the ``FakeTranscriber`` (selected via
``TRANSCRIBER=fake``). This is what lets every test — including the full request
flow — run in CI in seconds without a GPU, a model download, RabbitMQ, or Mongo.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

# Configure the environment *before* importing app modules so settings pick it up.
os.environ.update(
    {
        "TRANSCRIBER": "fake",
        "STORAGE_BACKEND": "local",
        "METRICS_ENABLED": "false",
        "LOG_JSON": "false",
        "MONGO_DATABASE": "mediascribe_test",
    }
)


def _patch_mongomock_kwargs() -> None:
    """Compatibility shim: Beanie calls ``list_collection_names`` with kwargs
    (``authorizedCollections``, ``nameOnly``) that mongomock doesn't accept.
    Wrap it to drop unknown kwargs so the in-memory DB matches real MongoDB's
    signature. Applied once, idempotently.
    """
    from mongomock.database import Database

    if getattr(Database.list_collection_names, "_patched", False):
        return
    original = Database.list_collection_names

    def patched(self, *args, **kwargs):  # noqa: ANN001
        return original(self)

    patched._patched = True  # type: ignore[attr-defined]
    Database.list_collection_names = patched  # type: ignore[method-assign]


@pytest_asyncio.fixture
async def init_db():
    """Initialize Beanie against an in-memory Mongo for each test."""
    from beanie import init_beanie
    from mongomock_motor import AsyncMongoMockClient

    from app.domain.models import Job

    _patch_mongomock_kwargs()
    client = AsyncMongoMockClient()
    await init_beanie(database=client["mediascribe_test"], document_models=[Job])
    yield
    # Each test gets a fresh client, so no teardown beyond GC is required.


@pytest.fixture
def storage(tmp_path):
    from app.storage.local import LocalStorage

    return LocalStorage(str(tmp_path / "uploads"))


@pytest.fixture
def settings():
    from app.config import Settings

    return Settings()


@pytest.fixture
def enqueue_spy():
    """A fake enqueue that records job ids instead of hitting Celery."""
    calls: list[str] = []
    return calls.append, calls
