"""Real PostgreSQL coverage for AdminRepository."""

from __future__ import annotations

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.db.session import Database
from app.domain.profiles import Profile, ProfileRole
from app.repositories.admin import AdminRepository

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
def repository() -> AdminRepository:
    return AdminRepository()


async def test_admin_repository_users_page(database: Database, repository: AdminRepository) -> None:
    async with database.sessions() as session, session.begin():
        user1 = Profile(
            auth_user_id=uuid4(),
            email=f"admin_{uuid4()}@example.com",
            role=ProfileRole.ADMIN,
        )
        user2 = Profile(
            auth_user_id=uuid4(),
            email=f"user_{uuid4()}@example.com",
            role=ProfileRole.EMPLOYEE,
        )
        session.add_all([user1, user2])

    async with database.sessions() as session:
        users, total = await repository.users_page(session, page=1, page_size=10, query=user1.email)
        assert total >= 1
        assert any(u.email == user1.email for u in users)


async def test_admin_repository_user_counts(
    database: Database, repository: AdminRepository
) -> None:
    async with database.sessions() as session, session.begin():
        user1 = Profile(
            auth_user_id=uuid4(),
            email=f"admin_count_{uuid4()}@example.com",
            role=ProfileRole.ADMIN,
        )
        session.add(user1)

    async with database.sessions() as session:
        counts = await repository.user_counts(session)
        assert counts["total_users"] > 0
        assert counts["admin_users"] > 0
        assert counts["recently_created_users"] > 0


async def test_admin_repository_resume_counts(
    database: Database, repository: AdminRepository
) -> None:
    async with database.sessions() as session:
        counts = await repository.resume_counts(session)
        assert "total_resumes" in counts
        assert "active_resumes" in counts
        assert "users_with_resumes" in counts
        assert "parsed_candidate_profiles" in counts
