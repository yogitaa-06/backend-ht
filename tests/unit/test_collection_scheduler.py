import pytest

from app.core.config import Settings
from app.domain.jobs import JobSource
from app.jobs.registry import CollectorRegistry
from app.jobs.targets import CollectionTarget
from app.queue.scheduler import enabled_targets, schedule_due_collections, source_interval_minutes

pytestmark = pytest.mark.anyio


class FakeCollector:
    source = JobSource.DICE

    async def collect(self, target: CollectionTarget) -> list[object]:
        del target
        return []


class FakeRedis:
    def __init__(self, *, fail_query: str | None = None) -> None:
        self.fail_query = fail_query
        self.jobs: list[tuple[object, ...]] = []
        self.claims: list[tuple[object, ...]] = []

    async def set(self, *args: object, **kwargs: object) -> bool:
        self.claims.append((*args, kwargs))
        return True

    async def enqueue_job(self, *args: object, **kwargs: object) -> object:
        if self.fail_query is not None and self.fail_query in args:
            raise RuntimeError("queue unavailable for target")
        self.jobs.append((*args, kwargs))
        return object()


def collection_settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "job_collection_enabled": True,
        "job_collection_targets": [
            {"source": "dice", "query": "DevOps Engineer", "max_jobs": 20},
            {"source": "dice", "query": "Backend Engineer", "max_jobs": 20},
        ],
    }
    values.update(updates)
    return Settings(**values)  # type: ignore[arg-type]


def test_source_specific_intervals() -> None:
    settings = collection_settings(
        dice_collection_interval_minutes=10,
        linkedin_collection_interval_minutes=20,
        glassdoor_collection_interval_minutes=30,
    )

    assert source_interval_minutes(settings, JobSource.DICE) == 10
    assert source_interval_minutes(settings, JobSource.LINKEDIN) == 20
    assert source_interval_minutes(settings, JobSource.GLASSDOOR) == 30


def test_enabled_targets_deduplicates_exact_searches() -> None:
    settings = collection_settings(
        job_collection_targets=[
            {"source": "dice", "query": "DevOps Engineer"},
            {"source": "dice", "query": "DevOps Engineer"},
            {"source": "dice", "query": "Disabled", "enabled": False},
        ]
    )

    assert len(enabled_targets(settings)) == 1


async def test_scheduler_enqueues_registered_due_targets() -> None:
    registry = CollectorRegistry()
    registry.register(FakeCollector())
    redis = FakeRedis()

    result = await schedule_due_collections(
        {"settings": collection_settings(), "collector_registry": registry, "redis": redis}
    )

    assert result == {"status": "completed", "enqueued": 2, "failed": 0, "unavailable": 0}
    assert len(redis.jobs) == 2
    assert redis.claims[0][-1] == {"nx": True, "ex": 1800}


async def test_scheduler_isolates_enqueue_failures() -> None:
    registry = CollectorRegistry()
    registry.register(FakeCollector())
    redis = FakeRedis(fail_query="DevOps Engineer")

    result = await schedule_due_collections(
        {"settings": collection_settings(), "collector_registry": registry, "redis": redis}
    )

    assert result["enqueued"] == 1
    assert result["failed"] == 1


async def test_scheduler_does_not_enqueue_unregistered_sources() -> None:
    result = await schedule_due_collections(
        {
            "settings": collection_settings(),
            "collector_registry": CollectorRegistry(),
            "redis": FakeRedis(),
        }
    )

    assert result["enqueued"] == 0
    assert result["unavailable"] == 2
