import pytest

from app.jobs.locks import RedisCollectionLockManager

pytestmark = pytest.mark.anyio


class FakeRedis:
    def __init__(self, *, acquire: bool = True, release: int = 1) -> None:
        self.acquire = acquire
        self.release = release
        self.set_calls: list[tuple[object, ...]] = []
        self.eval_calls: list[tuple[object, ...]] = []

    async def set(self, *args: object, **kwargs: object) -> bool:
        self.set_calls.append((*args, kwargs))
        return self.acquire

    async def eval(self, *args: object) -> int:
        self.eval_calls.append(args)
        return self.release


async def test_lock_acquisition_and_safe_release() -> None:
    redis = FakeRedis()
    manager = RedisCollectionLockManager(  # type: ignore[arg-type]
        redis, ttl_seconds=120, namespace="hireandtech"
    )

    lease = await manager.acquire("target")

    assert lease is not None
    assert redis.set_calls[0][-1] == {"nx": True, "px": 120_000}
    assert await lease.release()
    assert await lease.release() is False
    assert len(redis.eval_calls) == 1


async def test_lock_rejection_returns_none() -> None:
    redis = FakeRedis(acquire=False)
    manager = RedisCollectionLockManager(  # type: ignore[arg-type]
        redis, ttl_seconds=120, namespace="hireandtech"
    )

    assert await manager.acquire("target") is None
