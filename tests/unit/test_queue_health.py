import pytest

from app.core.config import Settings
from app.queue import health

pytestmark = pytest.mark.anyio


class FakeRedis:
    def __init__(self, heartbeat: str | None = None, *, fail: bool = False) -> None:
        self.heartbeat = heartbeat
        self.fail = fail
        self.closed = False

    async def ping(self) -> bool:
        if self.fail:
            raise ConnectionError
        return True

    async def get(self, key: str) -> str | None:
        assert key == "hireandtech:jobs:health-check"
        return self.heartbeat

    async def aclose(self) -> None:
        self.closed = True


async def test_queue_health_is_unknown_when_redis_is_not_configured() -> None:
    result = await health.check_queue_health(Settings(_env_file=None, redis_url=None))

    assert result.redis == "unknown"
    assert result.worker == "unknown"


async def test_queue_health_requires_real_worker_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(health.Redis, "from_url", lambda *args, **kwargs: redis)

    result = await health.check_queue_health(
        Settings(_env_file=None, redis_url="redis://localhost:6379/0")
    )

    assert result.redis == "healthy"
    assert result.worker == "unknown"
    assert redis.closed


async def test_queue_health_reports_worker_only_with_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis("worker alive")
    monkeypatch.setattr(health.Redis, "from_url", lambda *args, **kwargs: redis)

    result = await health.check_queue_health(
        Settings(_env_file=None, redis_url="redis://localhost:6379/0")
    )

    assert result.redis == "healthy"
    assert result.worker == "healthy"


async def test_queue_health_isolates_redis_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis(fail=True)
    monkeypatch.setattr(health.Redis, "from_url", lambda *args, **kwargs: redis)

    result = await health.check_queue_health(
        Settings(_env_file=None, redis_url="redis://localhost:6379/0")
    )

    assert result.redis == "unavailable"
    assert result.worker == "unknown"
    assert redis.closed
