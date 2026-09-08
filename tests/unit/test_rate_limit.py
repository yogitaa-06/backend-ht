"""Bounded route-specific rate-limiting tests."""

from unittest.mock import AsyncMock

import pytest

from app.security.rate_limit import (
    BoundedMemoryRateLimitStore,
    RateLimitStoreError,
    RouteRateLimiter,
)

pytestmark = pytest.mark.anyio


async def test_requests_below_and_above_limit_return_retry_window() -> None:
    store = BoundedMemoryRateLimitStore(100, clock=lambda: 10.0)
    limiter = RouteRateLimiter(store, fail_closed=True)

    first = await limiter.check("auth", "192.0.2.1", limit=2, window_seconds=60)
    second = await limiter.check("auth", "192.0.2.1", limit=2, window_seconds=60)
    denied = await limiter.check("auth", "192.0.2.1", limit=2, window_seconds=60)

    assert first is not None and first.allowed
    assert second is not None and second.allowed
    assert denied is not None
    assert not denied.allowed
    assert denied.retry_after_seconds == 60


async def test_keys_do_not_interfere_between_ips_or_routes() -> None:
    limiter = RouteRateLimiter(BoundedMemoryRateLimitStore(100), fail_closed=True)

    await limiter.check("auth", "192.0.2.1", limit=1, window_seconds=60)

    other_ip = await limiter.check("auth", "192.0.2.2", limit=1, window_seconds=60)
    other_route = await limiter.check("admin", "192.0.2.1", limit=1, window_seconds=60)

    assert other_ip is not None and other_ip.allowed
    assert other_route is not None and other_route.allowed


async def test_store_capacity_is_bounded() -> None:
    store = BoundedMemoryRateLimitStore(2)
    for key in ("one", "two", "three"):
        await store.consume(key, limit=5, window_seconds=60)

    assert len(store._entries) == 2


async def test_unavailable_store_obeys_closed_and_open_policies() -> None:
    store = AsyncMock()
    store.consume.side_effect = RuntimeError("backend unavailable")

    with pytest.raises(RateLimitStoreError):
        await RouteRateLimiter(store, fail_closed=True).check(
            "auth", "192.0.2.1", limit=1, window_seconds=60
        )

    assert (
        await RouteRateLimiter(store, fail_closed=False).check(
            "auth", "192.0.2.1", limit=1, window_seconds=60
        )
        is None
    )
