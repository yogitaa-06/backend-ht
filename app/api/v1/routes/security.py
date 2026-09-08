"""Authenticated administrator API for IP policy and safe audit inspection."""

from ipaddress import IPv4Address, IPv6Address
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.core.config import Settings
from app.db.session import get_session
from app.domain.profiles import Profile
from app.schemas.security import (
    CurrentIpResponse,
    IpRuleCreate,
    IpRulePage,
    IpRuleResponse,
    IpRuleUpdate,
    SecurityAuditEventPage,
)
from app.security.ip import IpAddress, address_in_networks
from app.security.service import IpSecurityService, audit_context

router = APIRouter(prefix="/admin/security")


def get_ip_security_service(request: Request) -> IpSecurityService:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):  # pragma: no cover - app composition contract
        raise RuntimeError("application settings unavailable")
    return IpSecurityService(settings)


def get_resolved_client_ip(request: Request) -> IpAddress | None:
    value = getattr(request.state, "resolved_client_ip", None)
    return value if isinstance(value, (IPv4Address, IPv6Address)) else None


@router.get("/ip/current", response_model=CurrentIpResponse)
async def get_current_ip(
    request: Request,
    _: Annotated[Profile, Depends(require_admin)],
) -> CurrentIpResponse:
    """Return the trusted resolved address, never an untrusted raw header value."""
    client_ip = get_resolved_client_ip(request)
    settings: Settings = request.app.state.settings
    return CurrentIpResponse(
        ip=str(client_ip) if client_ip is not None else None,
        emergency_bypass=client_ip is not None
        and address_in_networks(client_ip, settings.ip_emergency_bypass_cidrs),
    )


@router.get("/ip-rules", response_model=IpRulePage)
async def list_ip_rules(
    _: Annotated[Profile, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[IpSecurityService, Depends(get_ip_security_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IpRulePage:
    items, total = await service.rules.list_page(session, offset=offset, limit=limit)
    return IpRulePage(items=items, total=total, offset=offset, limit=limit)


@router.post("/ip-rules", response_model=IpRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_ip_rule(
    payload: IpRuleCreate,
    request: Request,
    profile: Annotated[Profile, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[IpSecurityService, Depends(get_ip_security_service)],
) -> IpRuleResponse:
    rule = await service.create_rule(
        session,
        profile,
        audit_context(profile, get_resolved_client_ip(request), request.headers.get("user-agent")),
        **payload.model_dump(),
    )
    return IpRuleResponse.model_validate(rule)


@router.patch("/ip-rules/{rule_id}", response_model=IpRuleResponse)
async def update_ip_rule(
    rule_id: UUID,
    payload: IpRuleUpdate,
    request: Request,
    profile: Annotated[Profile, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[IpSecurityService, Depends(get_ip_security_service)],
) -> IpRuleResponse:
    rule = await service.update_rule(
        session,
        audit_context(profile, get_resolved_client_ip(request), request.headers.get("user-agent")),
        rule_id,
        cidr=payload.cidr,
        label=payload.label,
        description=payload.description,
        description_set="description" in payload.model_fields_set,
        enabled=payload.enabled,
        current_ip=get_resolved_client_ip(request),
    )
    return IpRuleResponse.model_validate(rule)


@router.delete("/ip-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ip_rule(
    rule_id: UUID,
    request: Request,
    profile: Annotated[Profile, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[IpSecurityService, Depends(get_ip_security_service)],
) -> Response:
    await service.delete_rule(
        session,
        audit_context(profile, get_resolved_client_ip(request), request.headers.get("user-agent")),
        rule_id,
        current_ip=get_resolved_client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit-events", response_model=SecurityAuditEventPage)
async def list_audit_events(
    _: Annotated[Profile, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[IpSecurityService, Depends(get_ip_security_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SecurityAuditEventPage:
    items, total = await service.audits.list_page(session, offset=offset, limit=limit)
    return SecurityAuditEventPage(items=items, total=total, offset=offset, limit=limit)
