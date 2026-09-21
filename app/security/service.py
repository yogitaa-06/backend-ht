"""Transactional administration of persistent IP rules and security audit events."""

import re
from dataclasses import dataclass
from uuid import UUID

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.profiles import Profile
from app.domain.security import IpAccessRule, SecurityAuditEvent, SecurityAuditEventType
from app.repositories.security import IpRuleRepository, SecurityAuditRepository
from app.security.ip import IpAddress, address_in_networks, normalize_ip, normalize_network

_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_SENSITIVE_TERMS = (
    "authorization",
    "bearer ",
    "cookie",
    "password",
    "secret",
    "token",
    "credential",
)


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Sanitized request attributes permitted in persistent security events."""

    actor_user_id: UUID | None
    request_ip: str | None
    user_agent: str | None


def sanitize_user_agent(value: str | None) -> str | None:
    """Bound audit input and remove control characters without retaining headers wholesale."""
    if value is None:
        return None
    sanitized = "".join(character for character in value if character.isprintable()).strip()
    if any(term in sanitized.casefold() for term in _SENSITIVE_TERMS) or _JWT_PATTERN.search(
        sanitized
    ):
        return "[redacted]"
    return sanitized[:512] or None


def add_audit_event(
    session: AsyncSession,
    event_type: SecurityAuditEventType,
    context: AuditContext,
    *,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    metadata: dict[str, object] | None = None,
) -> SecurityAuditEvent:
    """Append a bounded event; callers own the transaction and never store request headers."""
    safe_metadata: dict[str, object] = {}
    for key, value in list((metadata or {}).items())[:16]:
        safe_key = str(key)[:64]
        if any(term in safe_key.casefold() for term in _SENSITIVE_TERMS):
            continue
        if isinstance(value, str):
            safe_metadata[safe_key] = sanitize_user_agent(value)
        elif isinstance(value, (bool, int, float)) or value is None:
            safe_metadata[safe_key] = value
    event = SecurityAuditEvent(
        actor_user_id=context.actor_user_id,
        event_type=event_type,
        request_ip=context.request_ip,
        user_agent=sanitize_user_agent(context.user_agent),
        resource_type=resource_type[:64] if resource_type else None,
        resource_id=resource_id,
        event_metadata=safe_metadata,
    )
    session.add(event)
    return event


class IpSecurityService:
    """Own IP-rule invariants while repositories remain persistence-only."""

    def __init__(
        self,
        settings: Settings,
        *,
        rules: IpRuleRepository | None = None,
        audits: SecurityAuditRepository | None = None,
    ) -> None:
        self.settings = settings
        self.rules = rules or IpRuleRepository()
        self.audits = audits or SecurityAuditRepository()

    async def create_rule(
        self,
        session: AsyncSession,
        actor: Profile,
        context: AuditContext,
        *,
        cidr: str,
        label: str,
        description: str | None,
        enabled: bool,
    ) -> IpAccessRule:
        await self.rules.lock_mutations(session)
        normalized = str(normalize_network(cidr))
        if await self.rules.get_by_cidr(session, normalized) is not None:
            raise _conflict("An IP rule for this network already exists.")
        rule = IpAccessRule(
            cidr=normalized,
            label=label,
            description=description,
            enabled=enabled,
            created_by=actor.id,
        )
        session.add(rule)
        try:
            await session.flush()
            add_audit_event(
                session,
                SecurityAuditEventType.IP_RULE_CREATED,
                context,
                resource_type="ip_access_rule",
                resource_id=rule.id,
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise _conflict("An IP rule for this network already exists.") from None
        await session.refresh(rule)
        return rule

    async def update_rule(
        self,
        session: AsyncSession,
        context: AuditContext,
        rule_id: UUID,
        *,
        cidr: str | None,
        label: str | None,
        description: str | None,
        description_set: bool,
        enabled: bool | None,
        current_ip: IpAddress | None,
    ) -> IpAccessRule:
        await self.rules.lock_mutations(session)
        rule = await self._get_rule(session, rule_id)
        next_cidr = str(normalize_network(cidr)) if cidr is not None else str(rule.cidr)
        if next_cidr != str(rule.cidr):
            duplicate = await self.rules.get_by_cidr(session, next_cidr)
            if duplicate is not None and duplicate.id != rule.id:
                raise _conflict("An IP rule for this network already exists.")
        next_enabled = enabled if enabled is not None else rule.enabled
        await self._guard_lockout(
            session,
            rule_id=rule.id,
            current_ip=current_ip,
            target_cidr=next_cidr,
            target_enabled=next_enabled,
        )
        was_enabled = rule.enabled
        rule.cidr = next_cidr
        if label is not None:
            rule.label = label
        if description_set:
            rule.description = description
        rule.enabled = next_enabled
        event_type = (
            SecurityAuditEventType.IP_RULE_DISABLED
            if was_enabled and not next_enabled
            else SecurityAuditEventType.IP_RULE_UPDATED
        )
        add_audit_event(
            session,
            event_type,
            context,
            resource_type="ip_access_rule",
            resource_id=rule.id,
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise _conflict("An IP rule for this network already exists.") from None
        await session.refresh(rule)
        return rule

    async def delete_rule(
        self,
        session: AsyncSession,
        context: AuditContext,
        rule_id: UUID,
        *,
        current_ip: IpAddress | None,
    ) -> None:
        await self.rules.lock_mutations(session)
        rule = await self._get_rule(session, rule_id)
        await self._guard_lockout(
            session,
            rule_id=rule.id,
            current_ip=current_ip,
            target_cidr=str(rule.cidr),
            target_enabled=False,
        )
        add_audit_event(
            session,
            SecurityAuditEventType.IP_RULE_DELETED,
            context,
            resource_type="ip_access_rule",
            resource_id=rule.id,
            metadata={"cidr": str(rule.cidr)},
        )
        await session.delete(rule)
        await session.commit()

    async def _get_rule(self, session: AsyncSession, rule_id: UUID) -> IpAccessRule:
        rule = await self.rules.get(session, rule_id)
        if rule is None:
            raise ApplicationError(
                "NOT_FOUND", "The requested resource was not found.", status.HTTP_404_NOT_FOUND
            )
        return rule

    async def _guard_lockout(
        self,
        session: AsyncSession,
        *,
        rule_id: UUID,
        current_ip: IpAddress | None,
        target_cidr: str,
        target_enabled: bool,
    ) -> None:
        if not self.settings.ip_allowlist_enabled:
            return
        if current_ip is not None and address_in_networks(
            current_ip, self.settings.ip_emergency_bypass_cidrs
        ):
            return
        if current_ip is None:
            raise _conflict("The change could lock out the current administrator.")
        networks = [
            normalize_network(rule.cidr)
            for rule in await self.rules.list_enabled(session)
            if rule.id != rule_id
        ]
        if target_enabled:
            networks.append(normalize_network(target_cidr))
        if not address_in_networks(current_ip, networks):
            raise _conflict("The change could lock out the current administrator.")


def audit_context(
    profile: Profile | None, client_ip: IpAddress | None, user_agent: str | None
) -> AuditContext:
    return AuditContext(
        actor_user_id=profile.id if profile is not None else None,
        request_ip=str(normalize_ip(client_ip)) if client_ip is not None else None,
        user_agent=sanitize_user_agent(user_agent),
    )


def _conflict(message: str) -> ApplicationError:
    return ApplicationError("CONFLICT", message, status.HTTP_409_CONFLICT)
