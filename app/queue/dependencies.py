"""Queue dependencies for FastAPI routes."""

from collections.abc import AsyncIterator

from arq.connections import ArqRedis
from fastapi import Request

from app.core.config import Settings
from app.queue.client import create_queue_pool


async def get_redis(request: Request) -> AsyncIterator[ArqRedis]:
    """Provide a Redis connection pool for enqueuing jobs."""
    # Ensure a single pool exists for the application lifecycle
    if not hasattr(request.app.state, "redis_pool"):
        settings: Settings = request.app.state.settings
        request.app.state.redis_pool = await create_queue_pool(settings)

    yield request.app.state.redis_pool
