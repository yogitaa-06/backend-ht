"""Persistent IP access rules and append-oriented security audit events."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import CIDR, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base, IdentityTimestampMixin
from app.security.ip import normalize_network


class SecurityAuditEventType(StrEnum):
    IP_ACCESS_DENIED = "IP_ACCESS_DENIED"
    IP_RULE_CREATED = "IP_RULE_CREATED"
    IP_RULE_UPDATED = "IP_RULE_UPDATED"
    IP_RULE_DISABLED = "IP_RULE_DISABLED"
    IP_RULE_DELETED = "IP_RULE_DELETED"
    IP_EMERGENCY_BYPASS_USED = "IP_EMERGENCY_BYPASS_USED"


class IpAccessRule(IdentityTimestampMixin, Base):
    """Administrator-owned normalized IPv4/IPv6 network authorization rule."""

    __tablename__ = "ip_access_rules"
    __table_args__ = (
        Index(
            "ix_ip_access_rules_enabled_cidr",
            "cidr",
            postgresql_using="gist",
            postgresql_ops={"cidr": "inet_ops"},
            postgresql_where=text("enabled"),
        ),
    )

    cidr: Mapped[str] = mapped_column(CIDR, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("hireandtech.profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    @validates("cidr")
    def normalize_cidr(self, _: str, value: str) -> str:
        return str(normalize_network(value))


class SecurityAuditEvent(Base):
    """Immutable-by-convention record of an IP-security decision or mutation."""

    __tablename__ = "security_audit_events"
    __table_args__ = (
        Index("ix_security_audit_events_created_at_id", "created_at", "id"),
        Index("ix_security_audit_events_event_type", "event_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("hireandtech.profiles.id", ondelete="SET NULL")
    )
    event_type: Mapped[SecurityAuditEventType] = mapped_column(
        Enum(
            SecurityAuditEventType,
            name="security_audit_event_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda events: [event.value for event in events],
        ),
        nullable=False,
    )
    request_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
