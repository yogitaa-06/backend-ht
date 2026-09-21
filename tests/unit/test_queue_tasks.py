from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest
from arq import Retry

from app.domain.jobs import JobSource
from app.jobs.collection import CoordinatorResult
from app.jobs.errors import TemporaryCollectionError
from app.jobs.normalization import RawSourceJob
from app.jobs.registry import CollectorRegistry
from app.jobs.targets import CollectionTarget
from app.queue.tasks import run_job_collection

pytestmark = pytest.mark.anyio


class AsyncContext(AbstractAsyncContextManager[object]):
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def begin(self) -> Self:
        return self


class FakeDatabase:
    def sessions(self) -> AsyncContext:
        return AsyncContext()


class FakeLease:
    def __init__(self) -> None:
        self.released = False

    async def release(self) -> bool:
        self.released = True
        return True


class FakeLocks:
    def __init__(self, lease: FakeLease | None) -> None:
        self.lease = lease

    async def acquire(self, key: str) -> FakeLease | None:
        assert len(key) == 24
        return self.lease


class FakeCollector:
    source = JobSource.DICE

    async def collect(self, target: CollectionTarget) -> list[RawSourceJob]:
        del target
        return []


class FakeCoordinator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def run(self, session: object, collector: object, target: object) -> CoordinatorResult:
        del session, collector, target
        if self.error:
            raise self.error
        now = datetime.now(UTC)
        return CoordinatorResult(now, now, 3, 3, 2, 0, 1, 0)


def context(
    *, registered: bool = True, lease: FakeLease | None = None, error: Exception | None = None
) -> dict[str, object]:
    registry = CollectorRegistry()
    if registered:
        registry.register(FakeCollector())
    return {
        "collector_registry": registry,
        "collection_locks": FakeLocks(lease),
        "database": FakeDatabase(),
        "collection_coordinator": FakeCoordinator(error),
    }


async def test_task_reports_source_unavailable_without_locking() -> None:
    result = await run_job_collection(
        context(registered=False), "dice", "DevOps Engineer", None, 10
    )

    assert result["status"] == "source_unavailable"
    assert result["lock_acquired"] is False


async def test_task_skips_when_distributed_lock_is_held() -> None:
    result = await run_job_collection(context(), "dice", "DevOps Engineer", None, 10)

    assert result["status"] == "skipped_locked"


async def test_task_returns_counts_and_releases_lock_after_success() -> None:
    lease = FakeLease()
    result = await run_job_collection(
        context(lease=lease), "dice", "DevOps Engineer", "United States", 10
    )

    assert result["status"] == "success"
    assert result["jobs_inserted"] == 2
    assert result["jobs_skipped"] == 1
    assert lease.released


async def test_task_releases_lock_after_permanent_failure() -> None:
    lease = FakeLease()
    result = await run_job_collection(
        context(lease=lease, error=RuntimeError("boom")),
        "dice",
        "DevOps Engineer",
        None,
        10,
    )

    assert result["status"] == "failed"
    assert lease.released


async def test_task_retries_temporary_failure_and_releases_lock() -> None:
    lease = FakeLease()
    with pytest.raises(Retry):
        await run_job_collection(
            context(lease=lease, error=TemporaryCollectionError("later", retry_after_seconds=5)),
            "dice",
            "DevOps Engineer",
            None,
            10,
        )

    assert lease.released
