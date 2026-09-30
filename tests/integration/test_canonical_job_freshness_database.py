"""Real PostgreSQL coverage for canonical job freshness and deactivation invariants."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.db.session import Database
from app.domain.jobs import CanonicalJob, Company, JobSourceObservation
from app.repositories.canonical_jobs import CanonicalJobRepository

TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.database,
    pytest.mark.anyio,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
    ),
]


@pytest.fixture(scope="module")
def database() -> Database:
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
    return Database(settings)


@pytest.fixture
def repository() -> CanonicalJobRepository:
    return CanonicalJobRepository()


async def test_deactivate_stale_sources_deactivates_job_when_no_active_sources_remain(
    database: Database, repository: CanonicalJobRepository
) -> None:
    now = datetime.now(UTC)
    stale_threshold = now - timedelta(hours=24)
    safety_window_start = now - timedelta(hours=2)

    job_id = uuid4()
    company_id = uuid4()

    async with database.sessions() as session, session.begin():
        company = Company(id=company_id, name="Stale Company", normalized_name="stale company")
        job = CanonicalJob(
            id=job_id,
            company_id=company_id,
            title="Stale Job",
            normalized_title="stale job",
            role_family="engineering",
            canonical_hash=str(uuid4()),
            is_active=True,
        )
        source = JobSourceObservation(
            job_id=job_id,
            source="dice",
            source_job_id=str(uuid4()),
            is_active=True,
            last_seen_at=stale_threshold - timedelta(hours=1),  # Very old
        )
        session.add_all([company, job, source])

    async with database.sessions() as session, session.begin():
        count = await repository.deactivate_stale_sources(
            session,
            source="dice",
            stale_threshold=stale_threshold,
            safety_window_start=safety_window_start,
        )
        assert count == 1

    async with database.sessions() as session:
        fetched_job = await session.scalar(select(CanonicalJob).where(CanonicalJob.id == job_id))
        fetched_source = await session.scalar(
            select(JobSourceObservation).where(JobSourceObservation.job_id == job_id)
        )

        assert fetched_source is not None
        assert fetched_source.is_active is False
        assert fetched_job is not None
        assert fetched_job.is_active is False


async def test_canonical_job_remains_active_if_another_source_is_active(
    database: Database, repository: CanonicalJobRepository
) -> None:
    now = datetime.now(UTC)
    stale_threshold = now - timedelta(hours=24)
    safety_window_start = now - timedelta(hours=2)

    job_id = uuid4()
    company_id = uuid4()

    async with database.sessions() as session, session.begin():
        company = Company(
            id=company_id, name="Multi Source Company", normalized_name="multi source company"
        )
        job = CanonicalJob(
            id=job_id,
            company_id=company_id,
            title="Multi Source Job",
            normalized_title="multi source job",
            role_family="engineering",
            canonical_hash=str(uuid4()),
            is_active=True,
        )
        source1 = JobSourceObservation(
            job_id=job_id,
            source="dice",
            source_job_id=str(uuid4()),
            is_active=True,
            last_seen_at=stale_threshold - timedelta(hours=1),  # Stale
        )
        source2 = JobSourceObservation(
            job_id=job_id,
            source="linkedin",
            source_job_id=str(uuid4()),
            is_active=True,
            last_seen_at=now,  # Active
        )
        session.add_all([company, job, source1, source2])

    async with database.sessions() as session, session.begin():
        # Only deactivating dice
        count = await repository.deactivate_stale_sources(
            session,
            source="dice",
            stale_threshold=stale_threshold,
            safety_window_start=safety_window_start,
        )
        assert count == 1

    async with database.sessions() as session:
        fetched_job = await session.scalar(select(CanonicalJob).where(CanonicalJob.id == job_id))

        # Job should remain active because linkedin source is active
        assert fetched_job is not None
        assert fetched_job.is_active is True
