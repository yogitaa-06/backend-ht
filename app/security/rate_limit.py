"""Capacity-bounded, injectable fixed-window rate-limiting foundation.

The default store is per-process and intentionally bounded. Deployments needing a
global limit can replace the store without changing middleware policy or keying.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

type Clock = Callable[[], float]

logger = logging.getLogger(__name__)


class RateLimitStoreError(Exception):
    """The configured counter store could not evaluate a request."""


@dataclass(slots=True)
class RateLimitDecision:
    """Result of consuming one request from a fixed window."""

    allowed: bool
    retry_after_seconds: int


class BoundedMemoryRateLimitStore:
    """Store fixed-window counters with strict key-capacity eviction."""

    def __init__(self, max_keys: int, *, clock: Clock = monotonic) -> None:
        self._max_keys = max_keys
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        async with self._lock:
            now = self._clock()
            started_at, count = self._entries.pop(key, (now, 0))
            if now - started_at >= window_seconds:
                started_at, count = now, 0
            count += 1
            self._entries[key] = (started_at, count)
            while len(self._entries) > self._max_keys:
                self._entries.popitem(last=False)
            retry_after = max(1, int(window_seconds - (now - started_at) + 0.999))
            return RateLimitDecision(count <= limit, retry_after)


class RateLimitStore(Protocol):
    async def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision: ...


class RouteRateLimiter:
    """Apply route-specific limits while honoring an explicit store-failure policy."""

    def __init__(self, store: RateLimitStore, *, fail_closed: bool) -> None:
        self._store = store
        self._fail_closed = fail_closed

    async def check(
        self,
        route_group: str,
        client_key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision | None:
        try:
            return await self._store.consume(
                f"{route_group}:{client_key}", limit=limit, window_seconds=window_seconds
            )
        except Exception as exc:
            logger.warning("rate_limit_store_failure", extra={"operation": "rate_limit"})
            if self._fail_closed:
                raise RateLimitStoreError from exc
            return None
