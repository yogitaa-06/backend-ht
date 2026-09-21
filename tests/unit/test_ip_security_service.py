"""Rule mutation, audit, conflict, and administrator lockout invariants."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.profiles import Profile, ProfileRole
from app.domain.security import IpAccessRule, SecurityAuditEvent, SecurityAuditEventType
from app.repositories.security import IpRuleRepository, SecurityAuditRepository
from app.security.ip import normalize_ip
from app.security.service import (
    AuditContext,
    IpSecurityService,
    add_audit_event,
    audit_context,
    sanitize_user_agent,
)

pytestmark = pytest.mark.anyio


def profile() -> Profile:
    return Profile(
        id=uuid4(), auth_user_id=uuid4(), email="admin@example.com", role=ProfileRole.ADMIN
    )


def rule(*, enabled: bool = True) -> IpAccessRule:
    now = datetime.now(UTC)
    return IpAccessRule(
        id=uuid4(),
        cidr="192.0.2.0/24",
        label="Office",
        enabled=enabled,
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


def session() -> MagicMock:
    return MagicMock(spec=AsyncSession)


def service(rules: object, *, enabled: bool = False) -> IpSecurityService:
    settings = Settings(_env_file=None, environment="test", ip_allowlist_enabled=enabled)
    return IpSecurityService(
        settings,
        rules=cast(IpRuleRepository, rules),
        audits=cast(SecurityAuditRepository, object()),
    )


async def test_create_rule_records_actor_and_audit_in_one_commit() -> None:
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get_by_cidr.return_value = None
    database_session = session()
    generated_id = uuid4()

    async def assign_id() -> None:
        created_rule = database_session.add.call_args_list[0].args[0]
        created_rule.id = generated_id

    database_session.flush.side_effect = assign_id
    actor = profile()

    created = await service(rules).create_rule(
        database_session,
        actor,
        audit_context(actor, normalize_ip("192.0.2.9"), "agent\x00safe"),
        cidr="192.0.2.9/24",
        label="Office",
        description=None,
        enabled=True,
    )

    assert created.cidr == "192.0.2.0/24"
    assert created.created_by == actor.id
    audit = cast(SecurityAuditEvent, database_session.add.call_args_list[1].args[0])
    assert audit.event_type is SecurityAuditEventType.IP_RULE_CREATED
    assert audit.actor_user_id == actor.id
    assert audit.user_agent == "agentsafe"
    rules.lock_mutations.assert_awaited_once_with(database_session)
    database_session.commit.assert_awaited_once()


async def test_duplicate_normalized_rule_returns_409() -> None:
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get_by_cidr.return_value = rule()
    actor = profile()

    with pytest.raises(ApplicationError) as exc_info:
        await service(rules).create_rule(
            session(),
            actor,
            audit_context(actor, normalize_ip("192.0.2.9"), None),
            cidr="192.0.2.9/24",
            label="Duplicate",
            description=None,
            enabled=True,
        )

    assert exc_info.value.status_code == 409


async def test_create_race_rolls_back_and_returns_conflict() -> None:
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get_by_cidr.return_value = None
    database_session = session()
    database_session.flush.side_effect = IntegrityError("statement", {}, Exception())
    actor = profile()

    with pytest.raises(ApplicationError) as exc_info:
        await service(rules).create_rule(
            database_session,
            actor,
            audit_context(actor, normalize_ip("192.0.2.9"), None),
            cidr="192.0.2.0/24",
            label="Race",
            description=None,
            enabled=True,
        )

    assert exc_info.value.status_code == 409
    database_session.rollback.assert_awaited_once()


async def test_update_changes_fields_and_records_disabled_event() -> None:
    current_rule = rule()
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get.return_value = current_rule
    rules.get_by_cidr.return_value = None
    database_session = session()
    actor = profile()

    updated = await service(rules).update_rule(
        database_session,
        audit_context(actor, normalize_ip("192.0.2.9"), None),
        current_rule.id,
        cidr="198.51.100.9/24",
        label="New office",
        description="Closed",
        description_set=True,
        enabled=False,
        current_ip=normalize_ip("192.0.2.9"),
    )

    assert updated.cidr == "198.51.100.0/24"
    assert updated.label == "New office"
    assert updated.description == "Closed"
    assert not updated.enabled
    event = cast(SecurityAuditEvent, database_session.add.call_args.args[0])
    assert event.event_type is SecurityAuditEventType.IP_RULE_DISABLED
    database_session.commit.assert_awaited_once()


async def test_update_duplicate_and_commit_race_return_conflict() -> None:
    current_rule = rule()
    duplicate = rule()
    duplicate.id = uuid4()
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get.return_value = current_rule
    rules.get_by_cidr.return_value = duplicate
    actor = profile()
    context = audit_context(actor, normalize_ip("192.0.2.9"), None)

    with pytest.raises(ApplicationError) as duplicate_error:
        await service(rules).update_rule(
            session(),
            context,
            current_rule.id,
            cidr="198.51.100.0/24",
            label=None,
            description=None,
            description_set=False,
            enabled=None,
            current_ip=normalize_ip("192.0.2.9"),
        )

    assert duplicate_error.value.status_code == 409

    rules.get_by_cidr.return_value = None
    database_session = session()
    database_session.commit.side_effect = IntegrityError("statement", {}, Exception())
    with pytest.raises(ApplicationError) as race_error:
        await service(rules).update_rule(
            database_session,
            context,
            current_rule.id,
            cidr="198.51.100.0/24",
            label=None,
            description=None,
            description_set=False,
            enabled=None,
            current_ip=normalize_ip("192.0.2.9"),
        )

    assert race_error.value.status_code == 409
    database_session.rollback.assert_awaited_once()


@pytest.mark.parametrize("operation", ["disable", "delete"])
async def test_final_matching_rule_cannot_lock_out_admin(operation: str) -> None:
    current_rule = rule()
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get.return_value = current_rule
    rules.list_enabled.return_value = [current_rule]
    database_session = session()
    secured_service = service(rules, enabled=True)
    actor = profile()
    context = audit_context(actor, normalize_ip("192.0.2.9"), None)

    with pytest.raises(ApplicationError) as exc_info:
        if operation == "disable":
            await secured_service.update_rule(
                database_session,
                context,
                current_rule.id,
                cidr=None,
                label=None,
                description=None,
                description_set=False,
                enabled=False,
                current_ip=normalize_ip("192.0.2.9"),
            )
        else:
            await secured_service.delete_rule(
                database_session,
                context,
                current_rule.id,
                current_ip=normalize_ip("192.0.2.9"),
            )

    assert exc_info.value.status_code == 409
    database_session.commit.assert_not_awaited()


async def test_ipv6_final_matching_rule_cannot_lock_out_admin() -> None:
    current_rule = rule()
    current_rule.cidr = "2001:db8::/64"
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get.return_value = current_rule
    rules.list_enabled.return_value = [current_rule]
    database_session = session()
    secured_service = service(rules, enabled=True)
    actor = profile()

    with pytest.raises(ApplicationError) as exc_info:
        await secured_service.update_rule(
            database_session,
            audit_context(actor, normalize_ip("2001:db8::9"), None),
            current_rule.id,
            cidr=None,
            label=None,
            description=None,
            description_set=False,
            enabled=False,
            current_ip=normalize_ip("2001:db8::9"),
        )

    assert exc_info.value.status_code == 409
    database_session.commit.assert_not_awaited()


async def test_emergency_network_permits_recovery_mutation() -> None:
    current_rule = rule()
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get.return_value = current_rule
    config = Settings(
        _env_file=None,
        environment="test",
        ip_allowlist_enabled=True,
        ip_emergency_bypass_cidrs=["198.51.100.7/32"],
    )
    secured_service = IpSecurityService(config, rules=rules)
    database_session = session()
    actor = profile()

    await secured_service.delete_rule(
        database_session,
        audit_context(actor, normalize_ip("198.51.100.7"), None),
        current_rule.id,
        current_ip=normalize_ip("198.51.100.7"),
    )

    database_session.delete.assert_awaited_once_with(current_rule)
    database_session.commit.assert_awaited_once()


async def test_missing_rule_returns_404() -> None:
    rules = AsyncMock(spec=IpRuleRepository)
    rules.get.return_value = None
    actor = profile()

    with pytest.raises(ApplicationError) as exc_info:
        await service(rules).delete_rule(
            session(),
            audit_context(actor, normalize_ip("192.0.2.9"), None),
            uuid4(),
            current_ip=normalize_ip("192.0.2.9"),
        )

    assert exc_info.value.status_code == 404


def test_user_agent_is_sanitized_and_bounded() -> None:
    assert sanitize_user_agent(None) is None
    assert sanitize_user_agent("\r\n") is None
    assert sanitize_user_agent("agent\r\nvalue") == "agentvalue"
    assert len(sanitize_user_agent("x" * 600) or "") == 512
    assert sanitize_user_agent("Bearer eyJheader.payload.signature") == "[redacted]"


def test_audit_metadata_drops_sensitive_and_nested_values() -> None:
    database_session = session()

    event = add_audit_event(
        database_session,
        SecurityAuditEventType.IP_ACCESS_DENIED,
        AuditContext(None, "192.0.2.9", None),
        metadata={
            "method": "GET",
            "access_token": "sensitive",
            "count": 2,
            "nested": {"unsafe": "value"},
        },
    )

    assert event.event_metadata == {"method": "GET", "count": 2}
