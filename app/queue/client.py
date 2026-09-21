"""Redis and ARQ connection helpers."""

from __future__ import annotations

from math import ceil

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import Settings


class RedisConfigurationError(RuntimeError):
    """A worker-required Redis setting is absent or invalid."""


def redis_settings_from_app(settings: Settings) -> RedisSettings:
    """Translate the secret application DSN without logging it."""
    if settings.redis_url is None:
        raise RedisConfigurationError(
            "HIREANDTECH_REDIS_URL is required to run the collection worker"
        )
    redis_settings = RedisSettings.from_dsn(settings.redis_url.get_secret_value())
    redis_settings.conn_timeout = ceil(settings.redis_connect_timeout_seconds)
    return redis_settings


async def create_queue_pool(settings: Settings) -> ArqRedis:
    """Create and verify an ARQ Redis pool for non-worker producers."""
    pool = await create_pool(redis_settings_from_app(settings))
    try:
        await pool.ping()
    except Exception:
        await pool.aclose(close_connection_pool=True)
        raise RuntimeError("Redis is unavailable") from None
    return pool
