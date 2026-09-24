from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import CanonicalJob, Company, JobSourceObservation
from app.jobs.normalization import RawSourceJob, normalize_job
from app.repositories.canonical_jobs import CanonicalJobRepository

pytestmark = pytest.mark.anyio


class MergeSession:
    def __init__(self, canonical: CanonicalJob) -> None:
        self.canonical = canonical

    async def get(self, model: type[object], identity: object) -> object | None:
        if model is CanonicalJob and identity == self.canonical.id:
            return self.canonical
        return None

    async def flush(self) -> None:
        return None


def _canonical(now: datetime) -> CanonicalJob:
    return CanonicalJob(
        id=uuid4(),
        title="Senior Security Engineer",
        normalized_title="senior security engineer",
        role_family="security",
        skills=[],
        first_seen_at=now,
        last_seen_at=now,
        is_active=True,
        canonical_hash="a" * 64,
    )


async def test_refresh_enriches_partial_job_and_preserves_values_from_null_update() -> None:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    canonical = _canonical(now)
    source = JobSourceObservation(
        id=uuid4(),
        job_id=canonical.id,
        source="dice",
        source_job_id="job-1",
        source_url="https://www.dice.com/job-detail/job-1",
        first_seen_at=now,
        last_seen_at=now,
        scraped_at=now,
        content_hash="a" * 64,
        is_active=True,
        raw_data={"legacy_global_job_id": str(uuid4())},
    )
    company = Company(id=uuid4(), name="Example Corp", normalized_name="example corp")
    rich = normalize_job(
        RawSourceJob(
            source="dice",
            external_job_id="job-1",
            title="Senior Security Engineer",
            company="Example Corp",
            location="New York, NY, US",
            url="https://www.dice.com/job-detail/job-1",
            description="Protect production systems.",
            salary_text="USD 150000 per year",
            employment_type="FULL_TIME",
            remote=False,
            posted_at=datetime(2026, 9, 11, 14, 32, 19, tzinfo=UTC),
            skills=("Python", "AWS"),
            raw_data={"@type": "JobPosting"},
        )
    )
    repository = CanonicalJobRepository()
    session = MergeSession(canonical)

    await repository.refresh_source(
        cast(AsyncSession, session),
        source,
        rich,
        company=company,
        observed_at=now,
        content_changed=True,
    )

    assert canonical.company_id == company.id
    assert canonical.location == "New York, NY, US"
    assert canonical.description == "Protect production systems."
    assert canonical.employment_type == "FULL_TIME"
    assert canonical.remote_type == "on_site"
    assert canonical.skills == ["aws", "python"]
    assert canonical.posted_at == datetime(2026, 9, 11, 14, 32, 19, tzinfo=UTC)
    assert source.source_posted_at == canonical.posted_at

    partial = normalize_job(
        RawSourceJob(
            source="dice",
            external_job_id="job-1",
            title="Senior Security Engineer",
        )
    )
    await repository.refresh_source(
        cast(AsyncSession, session),
        source,
        partial,
        company=None,
        observed_at=now,
        content_changed=True,
    )

    assert canonical.company_id == company.id
    assert canonical.location == "New York, NY, US"
    assert canonical.description == "Protect production systems."
    assert canonical.employment_type == "FULL_TIME"
    assert canonical.remote_type == "on_site"
    assert canonical.skills == ["aws", "python"]
    assert canonical.posted_at == datetime(2026, 9, 11, 14, 32, 19, tzinfo=UTC)
    assert source.source_url == "https://www.dice.com/job-detail/job-1"
    assert source.raw_data == {"@type": "JobPosting"}


async def test_refresh_repairs_canonical_even_when_source_hash_is_unchanged() -> None:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    canonical = _canonical(now)
    rich = normalize_job(
        RawSourceJob(
            source="dice",
            external_job_id="job-2",
            title="Senior Security Engineer",
            description="Available detail text.",
        )
    )
    source = JobSourceObservation(
        id=uuid4(),
        job_id=canonical.id,
        source="dice",
        source_job_id="job-2",
        first_seen_at=now,
        last_seen_at=now,
        scraped_at=now,
        content_hash=rich.content_hash,
        is_active=True,
        raw_data={"@type": "JobPosting"},
    )

    await CanonicalJobRepository().refresh_source(
        cast(AsyncSession, MergeSession(canonical)),
        source,
        rich,
        company=None,
        observed_at=now,
        content_changed=False,
    )

    assert canonical.description == "Available detail text."
