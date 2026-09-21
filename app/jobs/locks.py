"""Expiring Redis leases for distributed collection non-overlap."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from redis.asyncio import Redis

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class CollectionLease(Protocol):
    async def release(self) -> bool: ...


class CollectionLockManager(Protocol):
    async def acquire(self, key: str) -> CollectionLease | None: ...


@dataclass
class RedisCollectionLease:
    redis: Redis
    key: str
    token: str
    _released: bool = False

    async def release(self) -> bool:
        if self._released:
            return False
        operation = cast(Awaitable[Any], self.redis.eval(_RELEASE_SCRIPT, 1, self.key, self.token))
        released = bool(await operation)
        self._released = True
        return released


class RedisCollectionLockManager:
    """Acquire token-owned locks with TTL protection against worker crashes."""

    def __init__(self, redis: Redis, *, ttl_seconds: int, namespace: str) -> None:
        self._redis = redis
        self._ttl_ms = ttl_seconds * 1000
        self._namespace = namespace

    async def acquire(self, key: str) -> RedisCollectionLease | None:
        redis_key = f"{self._namespace}:collection-lock:{key}"
        token = secrets.token_urlsafe(32)
        acquired = await self._redis.set(redis_key, token, nx=True, px=self._ttl_ms)
        if not acquired:
            return None
        return RedisCollectionLease(self._redis, redis_key, token)
