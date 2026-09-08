"""Real-PostgreSQL profile persistence and constraint tests."""

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError, StatementError

from app.core.config import Settings
from app.db.session import Database
from app.domain.profiles import Profile, ProfileRole
from app.repositories.profiles import ProfileRepository

TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.database,
    pytest.mark.anyio,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
    ),
]


def migrated_settings() -> Settings:
    assert TEST_DATABASE_URL is not None
    environment = os.environ.copy()
    environment.update(
        HIREANDTECH_ENVIRONMENT="test",
        HIREANDTECH_DATABASE_URL=TEST_DATABASE_URL,
        HIREANDTECH_DATABASE_MIGRATION_URL=TEST_DATABASE_URL,
        HIREANDTECH_DATABASE_SSL_MODE="disable",
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "test database migration failed"
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        database_ssl_mode="disable",
    )


async def test_profile_persistence_repository_and_inactive_state() -> None:
    database = Database(migrated_settings())
    profile = Profile(
        auth_user_id=uuid4(),
        email=f"phase3-{uuid4()}@example.com",
        role=ProfileRole.ADMIN,
        is_active=False,
    )
    try:
        async with database.sessions() as session:
            session.add(profile)
            await session.commit()
            loaded = await ProfileRepository().get_by_auth_user_id(session, profile.auth_user_id)
            assert loaded is not None
            assert loaded.role is ProfileRole.ADMIN
            assert loaded.is_active is False
            await session.delete(loaded)
            await session.commit()
    finally:
        await database.close()


@pytest.mark.parametrize("duplicate_field", ["auth_user_id", "email"])
async def test_profile_unique_constraints(duplicate_field: str) -> None:
    database = Database(migrated_settings())
    auth_user_id = uuid4()
    email = f"phase3-{uuid4()}@example.com"
    first = Profile(auth_user_id=auth_user_id, email=email)
    second = Profile(
        auth_user_id=auth_user_id if duplicate_field == "auth_user_id" else uuid4(),
        email=email if duplicate_field == "email" else f"phase3-{uuid4()}@example.com",
    )
    try:
        async with database.sessions() as session:
            session.add(first)
            await session.commit()
            session.add(second)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
            await session.delete(first)
            await session.commit()
    finally:
        await database.close()


async def test_invalid_profile_role_is_rejected() -> None:
    database = Database(migrated_settings())
    profile = Profile(auth_user_id=uuid4(), email=f"phase3-{uuid4()}@example.com")
    profile.role = "owner"  # type: ignore[assignment]
    try:
        async with database.sessions() as session:
            session.add(profile)
            with pytest.raises(StatementError):
                await session.commit()
            await session.rollback()
    finally:
        await database.close()
