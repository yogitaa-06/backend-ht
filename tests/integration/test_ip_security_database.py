"""Real-PostgreSQL IP rule, audit, containment, and uniqueness tests."""

import os
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.session import Database
from app.domain.profiles import Profile, ProfileRole
from app.domain.security import (
    IpAccessRule,
    SecurityAuditEvent,
    SecurityAuditEventType,
)
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
    """Apply current migrations and return isolated test database settings."""
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


async def cleanup_test_records(
    database: Database,
    admin_id: UUID | None,
) -> None:
    """Delete test records in foreign-key-safe dependency order."""
    if admin_id is None:
        return

    async with database.sessions() as session:
        await session.execute(
            delete(SecurityAuditEvent).where(SecurityAuditEvent.actor_user_id == admin_id)
        )
        await session.execute(delete(IpAccessRule).where(IpAccessRule.created_by == admin_id))
        await session.execute(delete(Profile).where(Profile.id == admin_id))
        await session.commit()


async def test_persistent_rules_audit_containment_and_disabled_state() -> None:
    """Verify persistent CIDR matching, disabled rules, audits and uniqueness."""
    database = Database(migrated_settings())
    admin_id: UUID | None = None

    # Unique networks make the test repeatable even if an earlier interrupted
    # run left records in the disposable database.
    network_identifier = uuid4().int
    second_octet = (network_identifier >> 8) & 0xFF
    third_octet = network_identifier & 0xFF
    ipv6_segment = network_identifier & 0xFFFF

    ipv4_input = f"10.{second_octet}.{third_octet}.9/24"
    ipv4_network = f"10.{second_octet}.{third_octet}.0/24"
    ipv4_match = f"10.{second_octet}.{third_octet}.200"
    ipv4_miss = f"10.{second_octet}.{(third_octet + 1) % 256}.1"

    ipv6_input = f"fd00:{ipv6_segment:x}::9/64"
    ipv6_match = f"fd00:{ipv6_segment:x}::1"

    admin = Profile(
        auth_user_id=uuid4(),
        email=f"phase4-{uuid4()}@example.com",
        role=ProfileRole.ADMIN,
    )

    try:
        async with database.sessions() as session:
            session.add(admin)
            await session.flush()
            admin_id = admin.id

            enabled = IpAccessRule(
                cidr=ipv4_input,
                label="Office",
                enabled=True,
                created_by=admin_id,
            )
            disabled = IpAccessRule(
                cidr=ipv6_input,
                label="Old office",
                enabled=False,
                created_by=admin_id,
            )

            session.add_all([enabled, disabled])
            await session.flush()

            session.add(
                SecurityAuditEvent(
                    actor_user_id=admin_id,
                    event_type=SecurityAuditEventType.IP_RULE_CREATED,
                    request_ip=ipv4_match,
                    resource_type="ip_access_rule",
                    resource_id=enabled.id,
                )
            )
            await session.commit()

            repository = IpRuleRepository()

            assert enabled.cidr == ipv4_network
            assert await repository.matches(session, ipv4_match)
            assert not await repository.matches(session, ipv4_miss)
            assert not await repository.matches(session, ipv6_match)

            duplicate = IpAccessRule(
                cidr=ipv4_network,
                label="Duplicate",
                created_by=admin_id,
            )
            session.add(duplicate)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        try:
            await cleanup_test_records(database, admin_id)
        finally:
            await database.close()
