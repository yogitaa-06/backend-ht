"""Bounded Redis and worker-heartbeat health probes for administration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis as Redis

from app.core.config import Settings

HealthState = Literal["healthy", "unavailable", "unknown"]


@dataclass(frozen=True)
class QueueHealth:
    redis: HealthState
    worker: HealthState
    reason: str | None = None


async def check_queue_health(settings: Settings) -> QueueHealth:
    """Probe Redis and require an ARQ heartbeat before claiming worker health."""
    if settings.redis_url is None:
        return QueueHealth("unknown", "unknown", "Redis is not configured")

    client = Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=settings.redis_connect_timeout_seconds,
        socket_timeout=settings.redis_connect_timeout_seconds,
        decode_responses=True,
    )
    try:
        async with asyncio.timeout(settings.redis_connect_timeout_seconds):
            await client.ping()
            heartbeat = await client.get(f"{settings.job_collection_queue_name}:health-check")
    except Exception:
        return QueueHealth("unavailable", "unknown", "Redis probe failed")
    finally:
        await client.aclose()

    if heartbeat is None:
        return QueueHealth("healthy", "unknown", "No ARQ worker heartbeat was found")
    return QueueHealth("healthy", "healthy")
