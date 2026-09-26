import pytest

from app.core.config import Settings
from app.domain.jobs import JobSource
from app.jobs.registry import CollectorRegistry
from app.jobs.targets import CollectionTarget
from app.queue.scheduler import (
    _rotate_queries,
    enabled_targets,
    schedule_due_collections,
    source_interval_minutes,
)

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
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, *args: object, **kwargs: object) -> bool:
        self.store[str(key)] = str(value)
        self.claims.append((key, value, *args, kwargs))
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


async def test_rotate_queries_rotates_and_wraps_around() -> None:
    redis = FakeRedis()
    targets = [
        CollectionTarget(source=JobSource.GLASSDOOR, query=f"q{i}", location="US")
        for i in range(10)
    ]
    # Batch 1 (offset starts at 0): picks 0..5, next offset 6
    batch1 = await _rotate_queries(redis, "glassdoor", targets, batch_size=6)
    assert [t.query for t in batch1] == ["q0", "q1", "q2", "q3", "q4", "q5"]
    assert redis.store["hireandtech:query_offset:glassdoor"] == "6"

    # Batch 2: picks 6..9, 0..1 (wraps around), next offset 2
    batch2 = await _rotate_queries(redis, "glassdoor", targets, batch_size=6)
    assert [t.query for t in batch2] == ["q6", "q7", "q8", "q9", "q0", "q1"]
    assert redis.store["hireandtech:query_offset:glassdoor"] == "2"


async def test_scheduler_batches_glassdoor_targets() -> None:
    registry = CollectorRegistry()
    fake_gd = FakeCollector()
    fake_gd.source = JobSource.GLASSDOOR
    registry.register(fake_gd)
    redis = FakeRedis()

    settings = collection_settings(
        glassdoor_collection_batch_size=2,
        job_collection_targets=[
            {"source": "glassdoor", "query": f"role_{i}", "max_jobs": 10}
            for i in range(5)
        ],
    )

    result = await schedule_due_collections(
        {"settings": settings, "collector_registry": registry, "redis": redis}
    )

    assert result["status"] == "completed"
    assert result["enqueued"] == 2
    assert len(redis.jobs) == 2
