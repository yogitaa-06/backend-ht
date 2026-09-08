"""Focused SQLAlchemy access for IP rules and append-only audit events."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import cast

from app.domain.security import IpAccessRule, SecurityAuditEvent


class IpRuleRepository:
    async def get(self, session: AsyncSession, rule_id: UUID) -> IpAccessRule | None:
        return await session.get(IpAccessRule, rule_id)

    async def get_by_cidr(self, session: AsyncSession, cidr: str) -> IpAccessRule | None:
        result = await session.execute(select(IpAccessRule).where(IpAccessRule.cidr == cidr))
        return result.scalar_one_or_none()

    async def list_page(
        self, session: AsyncSession, *, offset: int, limit: int
    ) -> tuple[list[IpAccessRule], int]:
        rows = await session.scalars(
            select(IpAccessRule)
            .order_by(IpAccessRule.created_at, IpAccessRule.id)
            .offset(offset)
            .limit(limit)
        )
        total = await session.scalar(select(func.count()).select_from(IpAccessRule))
        return list(rows), int(total or 0)

    async def list_enabled(self, session: AsyncSession) -> list[IpAccessRule]:
        rows = await session.scalars(
            select(IpAccessRule)
            .where(IpAccessRule.enabled.is_(True))
            .order_by(IpAccessRule.created_at, IpAccessRule.id)
        )
        return list(rows)

    async def matches(
        self, session: AsyncSession, client_ip: str, *, exclude_rule_id: UUID | None = None
    ) -> bool:
        predicate = IpAccessRule.cidr.op(">>=")(cast(client_ip, INET))
        statement = select(IpAccessRule.id).where(IpAccessRule.enabled.is_(True), predicate)
        if exclude_rule_id is not None:
            statement = statement.where(IpAccessRule.id != exclude_rule_id)
        return (await session.scalar(statement.limit(1))) is not None


class SecurityAuditRepository:
    async def list_page(
        self, session: AsyncSession, *, offset: int, limit: int
    ) -> tuple[list[SecurityAuditEvent], int]:
        rows = await session.scalars(
            select(SecurityAuditEvent)
            .order_by(SecurityAuditEvent.created_at.desc(), SecurityAuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = await session.scalar(select(func.count()).select_from(SecurityAuditEvent))
        return list(rows), int(total or 0)
