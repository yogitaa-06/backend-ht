"""Real PostgreSQL coverage for canonical Dice ingestion invariants."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.domain.jobs import CanonicalJob, Company, JobSourceObservation
from app.jobs.ingestion import CanonicalJobIngestionService
from app.jobs.normalization import NormalizedJob, RawSourceJob, normalize_job
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


def _settings() -> Settings:
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
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        database_ssl_mode="disable",
    )


def _job(seed: str, company: str, *, description: str = "Initial description") -> NormalizedJob:
    return normalize_job(
        RawSourceJob(
            source="dice",
            external_job_id=f"phase1a-{seed}",
            title="Senior Python Engineer",
            company=company,
            location="Seattle, WA",
            url=f"https://www.dice.com/job-detail/phase1a-{seed}",
            description=description,
            posted_at=datetime(2026, 9, 20, tzinfo=UTC),
            raw_data={"test_seed": seed},
        )
    )


class FailingSourceRepository(CanonicalJobRepository):
    async def create_source(
        self,
        session: AsyncSession,
        job: NormalizedJob,
        *,
        canonical_job: CanonicalJob,
        observed_at: datetime,
    ) -> JobSourceObservation:
        del session, job, canonical_job, observed_at
        raise RuntimeError("injected source persistence failure")


async def _counts(database: Database, source_job_id: str) -> tuple[int, int, int]:
    async with database.sessions() as session:
        source = await session.scalar(
            select(JobSourceObservation).where(
                JobSourceObservation.source == "dice",
                JobSourceObservation.source_job_id == source_job_id,
            )
        )
        if source is None:
            return 0, 0, 0
        jobs = int(
            await session.scalar(
                select(func.count())
                .select_from(CanonicalJob)
                .where(CanonicalJob.id == source.job_id)
            )
            or 0
        )
        companies = int(
            await session.scalar(
                select(func.count())
                .select_from(Company)
                .join(CanonicalJob)
                .where(CanonicalJob.id == source.job_id)
            )
            or 0
        )
        return companies, jobs, 1


async def test_canonical_dice_ingestion_is_transactional_and_concurrency_safe() -> None:
    database = Database(_settings())
    seed = uuid4().hex
    source_job_id = f"phase1a-{seed}"
    company_name = f"Phase 1A Company {seed}"
    rollback_seed = uuid4().hex
    rollback_company = f"Rollback Company {rollback_seed}"
    job = _job(seed, company_name)

    async def ingest_once() -> None:
        async with database.sessions() as session, session.begin():
            await CanonicalJobIngestionService().ingest(session, job)

    try:
        await asyncio.gather(ingest_once(), ingest_once())
        assert await _counts(database, source_job_id) == (1, 1, 1)

        async with database.sessions() as session, session.begin():
            observation = await session.scalar(
                select(JobSourceObservation).where(
                    JobSourceObservation.source == "dice",
                    JobSourceObservation.source_job_id == source_job_id,
                )
            )
            assert observation is not None
            first_seen = observation.first_seen_at
            first_hash = observation.content_hash
            await CanonicalJobIngestionService().ingest(
                session, _job(seed, company_name, description="Changed description")
            )
            assert observation.first_seen_at == first_seen
            assert observation.content_hash != first_hash

        async with database.sessions() as session:
            existing = await session.scalar(
                select(JobSourceObservation).where(
                    JobSourceObservation.source == "dice",
                    JobSourceObservation.source_job_id == source_job_id,
                )
            )
            assert existing is not None
            session.add(
                JobSourceObservation(
                    job_id=existing.job_id,
                    source="dice",
                    source_job_id=source_job_id,
                    content_hash="f" * 64,
                    raw_data={},
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        with pytest.raises(RuntimeError, match="injected source persistence failure"):
            async with database.sessions() as session, session.begin():
                await CanonicalJobIngestionService(FailingSourceRepository()).ingest(
                    session, _job(rollback_seed, rollback_company)
                )
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Company)
                    .where(Company.normalized_name == rollback_company.casefold())
                )
                == 0
            )
    finally:
        async with database.sessions() as session, session.begin():
            job_ids = list(
                await session.scalars(
                    select(JobSourceObservation.job_id).where(
                        JobSourceObservation.source == "dice",
                        JobSourceObservation.source_job_id.in_(
                            (source_job_id, f"phase1a-{rollback_seed}")
                        ),
                    )
                )
            )
            await session.execute(
                delete(JobSourceObservation).where(JobSourceObservation.job_id.in_(job_ids))
            )
            await session.execute(delete(CanonicalJob).where(CanonicalJob.id.in_(job_ids)))
            await session.execute(
                delete(Company).where(
                    Company.normalized_name.in_(
                        (company_name.casefold(), rollback_company.casefold())
                    )
                )
            )
        await database.close()
