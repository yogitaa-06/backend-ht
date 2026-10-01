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


async def test_admin_repository_resumes_page(
    database: Database, repository: AdminRepository
) -> None:
    from app.domain.resumes import Resume, ResumeStatus

    async with database.sessions() as session, session.begin():
        user = Profile(auth_user_id=uuid4(), email=f"res_{uuid4()}@example.com")
        session.add(user)
        await session.flush()
        resume = Resume(
            owner_profile_id=user.id,
            original_filename="resume.pdf",
            storage_bucket="resumes",
            storage_object_key=f"key_{uuid4()}",
            content_type="application/pdf",
            size_bytes=1024,
            sha256="a" * 64,
            status=ResumeStatus.UPLOADED,
        )
        session.add(resume)

    async with database.sessions() as session:
        rows, total = await repository.resumes_page(session, page=1, page_size=10)
        assert total > 0
        assert len(rows) > 0
        assert isinstance(rows[0][0], Resume)


async def test_admin_repository_resume(database: Database, repository: AdminRepository) -> None:
    from app.domain.resumes import Resume, ResumeStatus

    async with database.sessions() as session, session.begin():
        user = Profile(auth_user_id=uuid4(), email=f"res2_{uuid4()}@example.com")
        session.add(user)
        await session.flush()
        resume = Resume(
            owner_profile_id=user.id,
            original_filename="resume2.pdf",
            storage_bucket="resumes",
            storage_object_key=f"key2_{uuid4()}",
            content_type="application/pdf",
            size_bytes=1024,
            sha256="b" * 64,
            status=ResumeStatus.UPLOADED,
        )
        session.add(resume)

    async with database.sessions() as session:
        result = await repository.resume(session, resume.id)
        assert result is not None
        assert result[0].id == resume.id

        missing = await repository.resume(session, uuid4())
        assert missing is None


async def test_admin_repository_security_count(
    database: Database, repository: AdminRepository
) -> None:
    async with database.sessions() as session:
        count = await repository.security_count(session)
        assert count == 0
