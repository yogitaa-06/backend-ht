from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import CanonicalJob, Company, JobSourceObservation
from app.jobs.ingestion import CanonicalJobIngestionService, IngestionAction
from app.jobs.normalization import NormalizedJob, RawSourceJob, normalize_job

pytestmark = pytest.mark.anyio


class FakeSession:
    def __init__(self, repository: FakeCanonicalRepository) -> None:
        self.repository = repository

    async def get(self, model: type[object], identity: UUID) -> object | None:
        if model is CanonicalJob:
            return self.repository.jobs.get(identity)
        if model is Company:
            return self.repository.companies_by_id.get(identity)
        return None


class FakeCanonicalRepository:
    def __init__(self) -> None:
        self.companies: dict[str, Company] = {}
        self.companies_by_id: dict[UUID, Company] = {}
        self.jobs: dict[UUID, CanonicalJob] = {}
        self.sources: dict[tuple[str, str], JobSourceObservation] = {}
        self.locks: list[tuple[str, str]] = []
        self.content_writes = 0

    async def lock_source_identity(
        self, session: object, *, source: str, source_job_id: str
    ) -> None:
        del session
        self.locks.append((source, source_job_id))

    async def get_source(
        self, session: object, *, source: str, source_job_id: str
    ) -> JobSourceObservation | None:
        del session
        return self.sources.get((source, source_job_id))

    async def resolve_company(
        self, session: object, *, name: str, normalized_name: str
    ) -> tuple[Company, bool]:
        del session
        company = self.companies.get(normalized_name)
        if company is not None:
            return company, False
        company = Company(id=uuid4(), name=name, normalized_name=normalized_name)
        self.companies[normalized_name] = company
        self.companies_by_id[company.id] = company
        return company, True

    async def find_job_by_source_url(
        self, session: object, *, source: str, source_url: str | None
    ) -> CanonicalJob | None:
        del session
        for observation in self.sources.values():
            if observation.source == source and observation.source_url == source_url:
                return self.jobs[observation.job_id]
        return None

    async def create_job(
        self,
        session: object,
        job: NormalizedJob,
        *,
        company: Company | None,
        observed_at: datetime,
    ) -> CanonicalJob:
        del session
        canonical = CanonicalJob(
            id=uuid4(),
            company_id=company.id if company else None,
            title=job.job_title,
            normalized_title=job.normalized_title,
            role_family=job.role_family,
            skills=job.skills,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            is_active=True,
            canonical_hash="a" * 64,
        )
        self.jobs[canonical.id] = canonical
        return canonical

    async def create_source(
        self,
        session: object,
        job: NormalizedJob,
        *,
        canonical_job: CanonicalJob,
        observed_at: datetime,
    ) -> JobSourceObservation:
        del session
        source = JobSourceObservation(
            id=uuid4(),
            job_id=canonical_job.id,
            source=job.source,
            source_job_id=job.external_job_id,
            source_url=job.job_url,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            scraped_at=observed_at,
            content_hash=job.content_hash,
            is_active=True,
            raw_data=job.raw_data,
        )
        self.sources[(job.source, job.external_job_id)] = source
        return source

    async def refresh_source(
        self,
        session: object,
        source: JobSourceObservation,
        job: NormalizedJob,
        *,
        company: Company | None,
        observed_at: datetime,
        content_changed: bool,
    ) -> None:
        del session, company
        source.last_seen_at = observed_at
        source.scraped_at = observed_at
        self.jobs[source.job_id].last_seen_at = observed_at
        if content_changed:
            self.content_writes += 1
            source.content_hash = job.content_hash
            self.jobs[source.job_id].description = job.description

    async def touch_sources_seen(
        self,
        session: object,
        *,
        source: str,
        source_job_ids: tuple[str, ...],
        observed_at: datetime,
    ) -> int:
        del session
        for source_job_id in source_job_ids:
            observation = self.sources[(source, source_job_id)]
            observation.last_seen_at = observed_at
            self.jobs[observation.job_id].last_seen_at = observed_at
        return len(source_job_ids)


def _job(
    source_job_id: str,
    *,
    company: str = "ABC Technologies",
    title: str = "Senior Python Engineer",
    url: str | None = None,
    description: str = "Build reliable Python services.",
) -> NormalizedJob:
    return normalize_job(
        RawSourceJob(
            source="dice",
            external_job_id=source_job_id,
            title=title,
            company=company,
            location="New York, NY",
            url=url or f"https://www.dice.com/job-detail/{source_job_id}?utm_source=test",
            description=description,
            posted_at=datetime(2026, 9, 20, tzinfo=UTC),
            raw_data={"id": source_job_id},
        )
    )


async def test_new_and_reobserved_dice_job_preserve_identity_and_first_seen() -> None:
    times = iter(
        (
            datetime(2026, 9, 21, tzinfo=UTC),
            datetime(2026, 9, 21, 1, tzinfo=UTC),
        )
    )
    repository = FakeCanonicalRepository()
    service = CanonicalJobIngestionService(repository, clock=lambda: next(times))  # type: ignore[arg-type]
    session = FakeSession(repository)

    first = await service.ingest(session, _job("123"))  # type: ignore[arg-type]
    first_seen = first.source.first_seen_at
    second = await service.ingest(session, _job("123"))  # type: ignore[arg-type]

    assert first.action is IngestionAction.CREATED
    assert second.action is IngestionAction.REOBSERVED
    assert len(repository.companies) == len(repository.jobs) == len(repository.sources) == 1
    assert second.job.id == first.job.id
    assert second.source.id == first.source.id
    assert second.source.first_seen_at == first_seen
    assert second.source.last_seen_at == datetime(2026, 9, 21, 1, tzinfo=UTC)
    assert second.source.scraped_at == datetime(2026, 9, 21, 1, tzinfo=UTC)
    assert repository.content_writes == 0


async def test_company_reuse_does_not_merge_distinct_dice_requisitions() -> None:
    repository = FakeCanonicalRepository()
    service = CanonicalJobIngestionService(repository)  # type: ignore[arg-type]
    session = FakeSession(repository)

    await service.ingest(session, _job("123"))  # type: ignore[arg-type]
    await service.ingest(session, _job("456", title="Backend Platform Engineer"))  # type: ignore[arg-type]

    assert len(repository.companies) == 1
    assert len(repository.jobs) == 2
    assert len(repository.sources) == 2


async def test_equal_job_fields_are_ambiguous_without_shared_source_identity() -> None:
    repository = FakeCanonicalRepository()
    service = CanonicalJobIngestionService(repository)  # type: ignore[arg-type]
    session = FakeSession(repository)

    await service.ingest(session, _job("123"))  # type: ignore[arg-type]
    await service.ingest(session, _job("456"))  # type: ignore[arg-type]

    assert len(repository.jobs) == 2


async def test_different_companies_are_not_merged() -> None:
    repository = FakeCanonicalRepository()
    service = CanonicalJobIngestionService(repository)  # type: ignore[arg-type]
    session = FakeSession(repository)

    await service.ingest(session, _job("123", company="ABC"))  # type: ignore[arg-type]
    await service.ingest(session, _job("456", company="XYZ"))  # type: ignore[arg-type]

    assert len(repository.companies) == 2
    assert len(repository.jobs) == 2


async def test_content_change_updates_without_changing_identity() -> None:
    repository = FakeCanonicalRepository()
    service = CanonicalJobIngestionService(repository)  # type: ignore[arg-type]
    session = FakeSession(repository)
    first = await service.ingest(session, _job("123"))  # type: ignore[arg-type]

    changed = await service.ingest(
        cast(AsyncSession, session),
        _job("123", description="Updated responsibilities and requirements."),
    )

    assert changed.action is IngestionAction.UPDATED
    assert changed.job.id == first.job.id
    assert changed.source.id == first.source.id
    assert repository.content_writes == 1
    assert changed.job.description == "Updated responsibilities and requirements."


async def test_discovery_touch_does_not_fabricate_a_detail_scrape() -> None:
    first_time = datetime(2026, 9, 21, tzinfo=UTC)
    second_time = first_time + timedelta(minutes=30)
    times = iter((first_time, second_time))
    repository = FakeCanonicalRepository()
    service = CanonicalJobIngestionService(repository, clock=lambda: next(times))  # type: ignore[arg-type]
    session = FakeSession(repository)
    first = await service.ingest(session, _job("123"))  # type: ignore[arg-type]

    await service.touch_seen(session, source="dice", source_job_ids=["123"])  # type: ignore[arg-type]

    assert first.source.last_seen_at == second_time
    assert first.source.scraped_at == first_time
