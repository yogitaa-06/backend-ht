"""Real PostgreSQL coverage for GlobalJobRepository."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.db.session import Database
from app.jobs.normalization import NormalizedJob
from app.repositories.jobs import GlobalJobRepository, JobUpsertStatus

TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.database,
    pytest.mark.anyio,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
    ),
]


from collections.abc import AsyncIterator


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    assert TEST_DATABASE_URL is not None
    environment = os.environ.copy()
    environment.update(
        HIREANDTECH_ENVIRONMENT="test",
        HIREANDTECH_DATABASE_URL=TEST_DATABASE_URL,
        HIREANDTECH_DATABASE_MIGRATION_URL=TEST_DATABASE_URL,
        HIREANDTECH_DATABASE_SSL_MODE="disable",
    )
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert migrated.returncode == 0, "canonical test database migration failed"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        database_ssl_mode="disable",
    )
    db = Database(settings)
    yield db
    await db.close()


@pytest.fixture
def repository() -> GlobalJobRepository:
    return GlobalJobRepository()


def _dummy_normalized() -> NormalizedJob:
    return NormalizedJob(
        source="dice",
        external_job_id=str(uuid4()),
        job_title="Software Engineer",
        normalized_title="software engineer",
        role_family="engineering",
        company="Tech Corp",
        normalized_company="tech corp",
        location="Remote",
        normalized_location="remote",
        job_url="http://example.com",
        description="Great job",
        salary_text="$100k",
        employment_type="full-time",
        remote=True,
        skills=["Python"],
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_updated_at=None,
        experience_min_years=3,
        experience_max_years=5,
        experience_text="3-5 years",
        content_hash="hash1",
        raw_data={},
    )


async def test_upsert_and_get_existing(database: Database, repository: GlobalJobRepository) -> None:
    job = _dummy_normalized()
    async with database.sessions() as session, session.begin():
        result = await repository.upsert_with_outcome(session, job)
        assert result.status == JobUpsertStatus.INSERTED
        assert result.job.job_title == "Software Engineer"

    async with database.sessions() as session:
        existing = await repository.get_existing_by_external_ids(
            session, "dice", [job.external_job_id]
        )
        assert job.external_job_id in existing
        assert existing[job.external_job_id].job_title == "Software Engineer"


async def test_touch_seen(database: Database, repository: GlobalJobRepository) -> None:
    job = _dummy_normalized()
    async with database.sessions() as session, session.begin():
        await repository.upsert(session, job)

    async with database.sessions() as session, session.begin():
        count = await repository.touch_seen(
            session, "dice", [job.external_job_id], seen_at=datetime(2026, 2, 1, tzinfo=UTC)
        )
        assert count == 1

    async with database.sessions() as session:
        existing = await repository.get_existing_by_external_ids(
            session, "dice", [job.external_job_id]
        )
        assert existing[job.external_job_id].last_seen_at == datetime(2026, 2, 1, tzinfo=UTC)


async def test_search_jobs(database: Database, repository: GlobalJobRepository) -> None:
    from dataclasses import replace

    job1 = replace(_dummy_normalized(), role_family="design", remote=False)
    job2 = replace(_dummy_normalized(), role_family="engineering", remote=True)

    async with database.sessions() as session, session.begin():
        await repository.upsert(session, job1)
        await repository.upsert(session, job2)

    async with database.sessions() as session:
        # Search by role family
        jobs, total = await repository.search(session, role="design")
        assert total >= 1
        assert any(j.external_job_id == job1.external_job_id for j in jobs)

        # Search by remote
        jobs, total = await repository.search(session, remote=True)
        assert total >= 1
        assert any(j.external_job_id == job2.external_job_id for j in jobs)


async def test_upsert_updates_when_hash_changes(
    database: Database, repository: GlobalJobRepository
) -> None:
    job = _dummy_normalized()
    async with database.sessions() as session, session.begin():
        await repository.upsert(session, job)

    from dataclasses import replace

    job = replace(job, content_hash="hash2", job_title="Senior Software Engineer")
    async with database.sessions() as session, session.begin():
        result = await repository.upsert_with_outcome(session, job)
        assert result.status == JobUpsertStatus.UPDATED
        assert result.job.job_title == "Senior Software Engineer"


async def test_upsert_skips_when_hash_matches(
    database: Database, repository: GlobalJobRepository
) -> None:
    job = _dummy_normalized()
    async with database.sessions() as session, session.begin():
        await repository.upsert(session, job)
        result = await repository.upsert_with_outcome(session, job)
        assert result.status == JobUpsertStatus.SKIPPED


async def test_early_returns_on_empty_ids(
    database: Database, repository: GlobalJobRepository
) -> None:
    async with database.sessions() as session:
        existing = await repository.get_existing_by_external_ids(session, "dice", [])
        assert existing == {}

    async with database.sessions() as session, session.begin():
        touched = await repository.touch_seen(session, "dice", [])
        assert touched == 0


async def test_search_jobs_with_all_filters(
    database: Database, repository: GlobalJobRepository
) -> None:
    job = _dummy_normalized()
    async with database.sessions() as session, session.begin():
        await repository.upsert(session, job)

    async with database.sessions() as session:
        # Search query
        jobs, total = await repository.search(session, query="Software")
        assert total >= 1

        # Search role_families
        jobs, total = await repository.search(session, role_families=["engineering"])
        assert total >= 1

        # Search location
        jobs, total = await repository.search(session, location="Remote")
        assert total >= 1

        # Search employment_type
        jobs, total = await repository.search(session, employment_type="full-time")
        assert total >= 1


async def test_by_id_and_stats(database: Database, repository: GlobalJobRepository) -> None:
    job = _dummy_normalized()
    async with database.sessions() as session, session.begin():
        persisted = await repository.upsert(session, job)

    async with database.sessions() as session:
        fetched = await repository.by_id(session, persisted.id)
        assert fetched is not None
        assert fetched.id == persisted.id

        stats = await repository.stats(session)
        assert stats["total_jobs"] >= 1
        assert stats["active_jobs"] >= 1
        assert stats["jobs_added_last_24_hours"] >= 1
        assert "dice" in stats["jobs_by_source"]
        assert "engineering" in stats["jobs_by_role_family"]
