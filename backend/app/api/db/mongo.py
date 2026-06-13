"""MongoDB initialization.

Two access paths, by design:

* the **API** uses Motor (async) + Beanie, initialized during the app lifespan;
* the **worker** uses a synchronous pymongo client (Celery tasks are sync), see
  ``app.worker.repository``.

Both read and write the same `jobs` collection.
"""

from __future__ import annotations

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.domain.models import Job

_client: AsyncIOMotorClient | None = None


async def init_mongo(settings: Settings) -> AsyncIOMotorClient:
    """Connect Motor and register Beanie document models. Call once at startup."""
    global _client
    _client = AsyncIOMotorClient(settings.mongo_uri)
    await init_beanie(
        database=_client[settings.mongo_database],
        document_models=[Job],
    )
    return _client


async def close_mongo() -> None:
    """Close the Motor client. Call during shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
