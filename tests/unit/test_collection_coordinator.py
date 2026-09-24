from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import GlobalJob, JobSource
from app.jobs.collection import CanonicalIngestion, CollectionCoordinator, LegacyJobPersistence
from app.jobs.normalization import DiscoveredSourceJob, RawSourceJob
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


class FakeCanonicalIngestion:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.ingested: list[str] = []
        self.touched: list[str] = []

    async def ingest(self, session: object, job: object) -> None:
        del session
        if self.fail:
            raise RuntimeError("canonical write failed")
        self.ingested.append(job.external_job_id)  # type: ignore[attr-defined]

    async def touch_seen(self, session: object, *, source: str, source_job_ids: list[str]) -> int:
        del session, source
        self.touched.extend(source_job_ids)
        return len(source_job_ids)


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


class DiscoveryCollector:
    source = JobSource.DICE

    def __init__(self, candidates: list[DiscoveredSourceJob]) -> None:
        self.candidates = candidates
        self.fetched: list[str] = []

    async def discover(self, target: CollectionTarget) -> list[DiscoveredSourceJob]:
        return self.candidates

    async def fetch_details(
        self,
        target: CollectionTarget,
        candidates: tuple[DiscoveredSourceJob, ...],
    ) -> list[RawSourceJob]:
        self.fetched = [candidate.external_job_id for candidate in candidates]
        return [
            RawSourceJob(target.source.value, candidate.external_job_id, candidate.title)
            for candidate in candidates
        ]


class DiscoveryRepository(FakeRepository):
    def __init__(self, existing: dict[str, object]) -> None:
        super().__init__()
        self.existing = existing
        self.touched: list[str] = []

    async def get_existing_by_external_ids(
        self, session: object, source: str, external_ids: list[str]
    ) -> dict[str, object]:
        return {
            external_id: self.existing[external_id]
            for external_id in external_ids
            if external_id in self.existing
        }

    async def touch_seen(self, session: object, source: str, external_ids: list[str]) -> int:
        self.touched.extend(external_ids)
        return len(external_ids)


async def test_coordinator_normalizes_and_reports_upsert_outcomes() -> None:
    canonical = FakeCanonicalIngestion()
    coordinator = CollectionCoordinator(
        cast(LegacyJobPersistence, FakeRepository()),
        cast(CanonicalIngestion, canonical),
    )
    target = CollectionTarget(source=JobSource.DICE, query="DevOps Engineer")

    result = await coordinator.run(cast(AsyncSession, FakeSession()), FakeCollector(), target)

    assert result.jobs_discovered == 3
    assert result.jobs_normalized == 3
    assert result.jobs_inserted == 1
    assert result.jobs_updated == 1
    assert result.jobs_skipped == 1
    assert result.jobs_failed == 0
    assert result.canonical_jobs_failed == 0
    assert canonical.ingested == ["0", "1", "2"]


async def test_coordinator_skips_recent_candidates_and_fetches_stale_once() -> None:
    now = datetime.now(UTC)
    recent = type("Existing", (), {"scraped_at": now - timedelta(hours=1)})()
    stale = type("Existing", (), {"scraped_at": now - timedelta(hours=7)})()
    candidates = [
        DiscoveredSourceJob("dice", "recent", "Recent Job"),
        DiscoveredSourceJob("dice", "recent", "Recent Job"),
        DiscoveredSourceJob("dice", "stale", "Stale Job"),
        DiscoveredSourceJob("dice", "new", "New Job"),
    ]
    collector = DiscoveryCollector(candidates)
    repository = DiscoveryRepository({"recent": recent, "stale": stale})

    canonical = FakeCanonicalIngestion()
    result = await CollectionCoordinator(
        cast(LegacyJobPersistence, repository), cast(CanonicalIngestion, canonical)
    ).run(
        cast(AsyncSession, FakeSession()),
        collector,
        CollectionTarget(source=JobSource.DICE, query="jobs"),
    )

    assert result.jobs_discovered == 3
    assert result.details_skipped_recent == 1
    assert collector.fetched == ["stale", "new"]
    assert repository.touched == ["recent"]
    assert canonical.touched == ["recent"]


async def test_coordinator_preserves_legacy_write_when_canonical_write_fails() -> None:
    result = await CollectionCoordinator(
        cast(LegacyJobPersistence, FakeRepository()),
        cast(CanonicalIngestion, FakeCanonicalIngestion(fail=True)),
    ).run(
        cast(AsyncSession, FakeSession()),
        FakeCollector(),
        CollectionTarget(source=JobSource.DICE, query="jobs"),
    )

    assert result.jobs_inserted == 1
    assert result.jobs_updated == 1
    assert result.jobs_skipped == 1
    assert result.jobs_failed == 0
    assert result.canonical_jobs_failed == 3
