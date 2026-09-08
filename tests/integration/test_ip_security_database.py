"""Real-PostgreSQL IP rule, audit, containment, and uniqueness tests."""

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.session import Database
from app.domain.profiles import Profile, ProfileRole
from app.domain.security import IpAccessRule, SecurityAuditEvent, SecurityAuditEventType
from app.repositories.security import IpRuleRepository

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


async def test_persistent_rules_audit_containment_and_disabled_state() -> None:
    database = Database(migrated_settings())
    admin = Profile(
        auth_user_id=uuid4(),
        email=f"phase4-{uuid4()}@example.com",
        role=ProfileRole.ADMIN,
    )
    try:
        async with database.sessions() as session:
            session.add(admin)
            await session.flush()
            enabled = IpAccessRule(
                cidr="192.0.2.9/24", label="Office", enabled=True, created_by=admin.id
            )
            disabled = IpAccessRule(
                cidr="2001:db8::9/64", label="Old office", enabled=False, created_by=admin.id
            )
            session.add_all([enabled, disabled])
            await session.flush()
            session.add(
                SecurityAuditEvent(
                    actor_user_id=admin.id,
                    event_type=SecurityAuditEventType.IP_RULE_CREATED,
                    request_ip="192.0.2.9",
                    resource_type="ip_access_rule",
                    resource_id=enabled.id,
                )
            )
            await session.commit()

            repository = IpRuleRepository()
            assert await repository.matches(session, "192.0.2.200")
            assert not await repository.matches(session, "198.51.100.1")
            assert not await repository.matches(session, "2001:db8::1")

            duplicate = IpAccessRule(cidr="192.0.2.0/24", label="Duplicate", created_by=admin.id)
            session.add(duplicate)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            await session.delete(enabled)
            await session.delete(disabled)
            audit_rows = await session.execute(
                delete(SecurityAuditEvent).where(SecurityAuditEvent.actor_user_id == admin.id)
            )
            _ = audit_rows
            await session.delete(admin)
            await session.commit()
    finally:
        await database.close()
