"""Persistence and schema invariants for Phase 4 security records."""

from uuid import uuid4

import pytest

from app.domain.security import IpAccessRule, SecurityAuditEvent
from app.schemas.security import IpRuleCreate, IpRuleUpdate


def test_ip_rule_normalizes_ipv4_and_ipv6_networks() -> None:
    ipv4 = IpAccessRule(cidr="192.0.2.9/24", label="Office", created_by=uuid4())
    ipv6 = IpAccessRule(cidr="2001:db8::9/64", label="Office v6", created_by=uuid4())

    assert ipv4.cidr == "192.0.2.0/24"
    assert ipv6.cidr == "2001:db8::/64"


def test_invalid_api_cidr_is_rejected() -> None:
    with pytest.raises(ValueError):
        IpRuleCreate(cidr="invalid", label="Invalid")

    with pytest.raises(ValueError):
        IpRuleUpdate(cidr="invalid")

    with pytest.raises(ValueError, match="at least one field"):
        IpRuleUpdate()


def test_rule_and_audit_tables_have_expected_constraints() -> None:
    rule_table = IpAccessRule.__table__
    audit_table = SecurityAuditEvent.__table__

    assert rule_table.schema == "hireandtech"
    assert rule_table.c.cidr.unique
    assert rule_table.c.created_by.foreign_keys
    assert audit_table.schema == "hireandtech"
    assert audit_table.c.metadata.nullable is False
    assert "authorization" not in audit_table.c
    assert "cookie" not in audit_table.c
