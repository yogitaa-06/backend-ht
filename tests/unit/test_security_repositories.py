"""Focused unit tests for Phase 4 SQLAlchemy repository contracts."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.security import IpAccessRule, SecurityAuditEvent, SecurityAuditEventType
from app.repositories.security import IpRuleRepository, SecurityAuditRepository

pytestmark = pytest.mark.anyio


def rule() -> IpAccessRule:
    now = datetime.now(UTC)
    return IpAccessRule(
        id=uuid4(),
        cidr="192.0.2.0/24",
        label="Office",
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


def audit() -> SecurityAuditEvent:
    return SecurityAuditEvent(
        id=uuid4(),
        event_type=SecurityAuditEventType.IP_ACCESS_DENIED,
        created_at=datetime.now(UTC),
    )


def session() -> MagicMock:
    return MagicMock(spec=AsyncSession)


async def test_rule_get_and_get_by_cidr() -> None:
    database_session = session()
    expected = rule()
    database_session.get.return_value = expected
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    database_session.execute.return_value = result
    repository = IpRuleRepository()

    assert await repository.get(database_session, expected.id) is expected
    assert await repository.get_by_cidr(database_session, expected.cidr) is expected


async def test_rule_pages_and_enabled_list() -> None:
    database_session = session()
    expected = rule()
    database_session.scalars.return_value = [expected]
    database_session.scalar.return_value = 1
    repository = IpRuleRepository()

    items, total = await repository.list_page(database_session, offset=0, limit=25)
    enabled = await repository.list_enabled(database_session)

    assert items == [expected]
    assert total == 1
    assert enabled == [expected]


async def test_match_supports_present_absent_and_excluded_rules() -> None:
    database_session = session()
    repository = IpRuleRepository()
    database_session.scalar.side_effect = [uuid4(), None]

    assert await repository.matches(database_session, "192.0.2.8")
    assert not await repository.matches(database_session, "192.0.2.8", exclude_rule_id=uuid4())


async def test_audit_page_is_returned_with_total() -> None:
    database_session = session()
    expected = audit()
    database_session.scalars.return_value = [expected]
    database_session.scalar.return_value = 1

    items, total = await SecurityAuditRepository().list_page(database_session, offset=0, limit=10)

    assert items == [expected]
    assert total == 1
