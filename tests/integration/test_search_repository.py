"""Real PostgreSQL coverage for SearchRepository."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.db.session import Database
from app.domain.search import JobSearch, JobSearchResult
from app.jobs.types import SearchStatus
from app.search.repository import SearchRepository

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
def database() -> Iterator[Database]:
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
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        _task = loop.create_task(db.close())
    except RuntimeError:
        asyncio.run(db.close())


@pytest.fixture
def repository() -> SearchRepository:
    return SearchRepository()


async def test_create_and_get_search(database: Database, repository: SearchRepository) -> None:
    from app.domain.profiles import Profile

    user_id = uuid4()
    profile = Profile(id=user_id, auth_user_id=uuid4(), email="test@example.com", is_active=True)
    search = JobSearch(
        user_id=user_id, status=SearchStatus.QUEUED, query="Software Engineer", requested_limit=10
    )
    async with database.sessions() as session, session.begin():
        session.add(profile)
        await repository.create_search(session, search)

    async with database.sessions() as session:
        fetched = await repository.get_search(session, search.id, user_id)
        assert fetched is not None
        assert fetched.id == search.id
        assert fetched.query == "Software Engineer"
        assert fetched.status == SearchStatus.QUEUED
        assert fetched.requested_limit == 10


async def test_get_search_enforces_ownership(
    database: Database, repository: SearchRepository
) -> None:
    from app.domain.profiles import Profile

    user_id = uuid4()
    profile = Profile(id=user_id, auth_user_id=uuid4(), email="test2@example.com", is_active=True)
    search = JobSearch(
        user_id=user_id,
        status=SearchStatus.QUEUED,
    )
    async with database.sessions() as session, session.begin():
        session.add(profile)
        await repository.create_search(session, search)

    async with database.sessions() as session:
        # Requesting with wrong user_id should return None
        fetched = await repository.get_search(session, search.id, uuid4())
        assert fetched is None


async def test_save_and_get_results(database: Database, repository: SearchRepository) -> None:
    from app.domain.profiles import Profile

    user_id = uuid4()
    profile = Profile(id=user_id, auth_user_id=uuid4(), email="test3@example.com", is_active=True)
    search = JobSearch(
        user_id=user_id,
        status=SearchStatus.COMPLETED,
    )

    # We need a job to reference in results
    from app.domain.jobs import CanonicalJob

    job1 = CanonicalJob(
        title="Job 1",
        normalized_title="job 1",
        role_family="engineering",
        canonical_hash="hash1",
    )
    job2 = CanonicalJob(
        title="Job 2",
        normalized_title="job 2",
        role_family="engineering",
        canonical_hash="hash2",
    )

    async with database.sessions() as session, session.begin():
        session.add(profile)
        session.add_all([job1, job2])
        await session.flush()

        await repository.create_search(session, search)

        results = [
            JobSearchResult(search_id=search.id, job_id=job1.id, rank=1, match_score=0.9),
            JobSearchResult(search_id=search.id, job_id=job2.id, rank=2, match_score=0.8),
        ]
        await repository.save_results(session, results)

    async with database.sessions() as session:
        items, total = await repository.get_results(session, search.id, page=1, page_size=1)
        assert total == 2
        assert len(items) == 1
        assert items[0].rank == 1
        assert items[0].job_id == job1.id

        items2, _total2 = await repository.get_results(session, search.id, page=2, page_size=1)
        assert len(items2) == 1
        assert items2[0].rank == 2
        assert items2[0].job_id == job2.id


async def test_clear_results(database: Database, repository: SearchRepository) -> None:
    from app.domain.profiles import Profile

    user_id = uuid4()
    profile = Profile(id=user_id, auth_user_id=uuid4(), email="test4@example.com", is_active=True)
    search = JobSearch(
        user_id=user_id,
        status=SearchStatus.COMPLETED,
    )

    from app.domain.jobs import CanonicalJob

    job1 = CanonicalJob(
        title="Job 1",
        normalized_title="job 1",
        role_family="engineering",
        canonical_hash="hash_clear_1",
    )

    async with database.sessions() as session, session.begin():
        session.add(profile)
        session.add(job1)
        await session.flush()

        await repository.create_search(session, search)
        results = [JobSearchResult(search_id=search.id, job_id=job1.id, rank=1, match_score=0.9)]
        await repository.save_results(session, results)

    async with database.sessions() as session, session.begin():
        await repository.clear_results(session, search.id)

    async with database.sessions() as session:
        items, total = await repository.get_results(session, search.id, page=1, page_size=10)
        assert total == 0
        assert len(items) == 0
