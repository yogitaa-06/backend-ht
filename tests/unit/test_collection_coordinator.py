from contextlib import AbstractAsyncContextManager
from types import TracebackType

import pytest

from app.domain.jobs import GlobalJob, JobSource
from app.jobs.collection import CollectionCoordinator
from app.jobs.normalization import RawSourceJob
from app.jobs.targets import CollectionTarget
from app.repositories.jobs import JobUpsertResult, JobUpsertStatus

pytestmark = pytest.mark.anyio


class NestedTransaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeSession:
    def begin_nested(self) -> NestedTransaction:
        return NestedTransaction()


class FakeRepository:
    def __init__(self) -> None:
        self.statuses = iter(
            (JobUpsertStatus.INSERTED, JobUpsertStatus.UPDATED, JobUpsertStatus.SKIPPED)
        )

    async def upsert_with_outcome(self, session: object, job: object) -> JobUpsertResult:
        del session, job
        return JobUpsertResult(GlobalJob(), next(self.statuses))


class FakeCollector:
    source = JobSource.DICE

    async def collect(self, target: CollectionTarget) -> list[RawSourceJob]:
        return [
            RawSourceJob(target.source.value, str(index), f"DevOps Engineer {index}")
            for index in range(3)
        ]


async def test_coordinator_normalizes_and_reports_upsert_outcomes() -> None:
    coordinator = CollectionCoordinator(FakeRepository())  # type: ignore[arg-type]
    target = CollectionTarget(source=JobSource.DICE, query="DevOps Engineer")

    result = await coordinator.run(FakeSession(), FakeCollector(), target)  # type: ignore[arg-type]

    assert result.jobs_discovered == 3
    assert result.jobs_normalized == 3
    assert result.jobs_inserted == 1
    assert result.jobs_updated == 1
    assert result.jobs_skipped == 1
    assert result.jobs_failed == 0
