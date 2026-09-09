"""Administrator API tests for IP rules, trusted current IP, and safe audit pages."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.security import get_ip_security_service
from app.auth.dependencies import require_admin
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.db.session import get_session
from app.domain.profiles import Profile, ProfileRole
from app.domain.security import IpAccessRule, SecurityAuditEvent, SecurityAuditEventType
from app.main import create_app
from app.security.service import IpSecurityService

pytestmark = pytest.mark.anyio

ADMIN = Profile(id=uuid4(), auth_user_id=uuid4(), email="admin@example.com", role=ProfileRole.ADMIN)
EMPLOYEE = Profile(
    id=uuid4(), auth_user_id=uuid4(), email="employee@example.com", role=ProfileRole.EMPLOYEE
)


def make_rule(*, cidr: str = "192.0.2.0/24", enabled: bool = True) -> IpAccessRule:
    now = datetime.now(UTC)
    return IpAccessRule(
        id=uuid4(),
        cidr=cidr,
        label="Office",
        description=None,
        enabled=enabled,
        created_by=ADMIN.id,
        created_at=now,
        updated_at=now,
    )


class FakeRules:
    def __init__(self, items: list[IpAccessRule] | None = None) -> None:
        self.items = items or []

    async def list_page(
        self, _: AsyncSession, *, offset: int, limit: int
    ) -> tuple[list[IpAccessRule], int]:
        return self.items[offset : offset + limit], len(self.items)


class FakeAudits:
    def __init__(self, items: list[SecurityAuditEvent] | None = None) -> None:
        self.items = items or []

    async def list_page(
        self, _: AsyncSession, *, offset: int, limit: int
    ) -> tuple[list[SecurityAuditEvent], int]:
        return self.items[offset : offset + limit], len(self.items)


class FakeService:
    def __init__(self) -> None:
        self.rules = FakeRules()
        self.audits = FakeAudits()
        self.create_rule = AsyncMock(side_effect=self._create)
        self.update_rule = AsyncMock(side_effect=self._update)
        self.delete_rule = AsyncMock(return_value=None)

    async def _create(self, _: object, actor: Profile, __: object, **values: Any) -> IpAccessRule:
        return make_rule(cidr=values["cidr"], enabled=values["enabled"])

    async def _update(self, _: object, __: object, rule_id: UUID, **values: Any) -> IpAccessRule:
        rule = make_rule(cidr=values["cidr"] or "192.0.2.0/24")
        rule.id = rule_id
        if values["enabled"] is not None:
            rule.enabled = values["enabled"]
        return rule


async def security_client(
    service: FakeService,
    *,
    profile: Profile | None,
    client_ip: str = "192.0.2.9",
) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=["testserver"],
        cors_allowed_origins=["http://testserver"],
        rate_limit_enabled=False,
    )
    application = create_app(settings)

    async def fake_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    if profile is not None:
        if profile.role is ProfileRole.ADMIN:
            application.dependency_overrides[require_admin] = lambda: profile
        else:

            async def reject_employee() -> Profile:
                raise ApplicationError("FORBIDDEN", "Access is not permitted.", 403)

            application.dependency_overrides[require_admin] = reject_employee
    application.dependency_overrides[get_session] = fake_session
    application.dependency_overrides[get_ip_security_service] = lambda: cast(
        IpSecurityService, service
    )
    transport = ASGITransport(app=application, client=(client_ip, 12345))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_security_api_requires_authentication() -> None:
    async for client in security_client(FakeService(), profile=None):
        response = await client.get("/api/v1/admin/security/ip-rules")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_security_api_rejects_non_admin() -> None:
    async for client in security_client(FakeService(), profile=EMPLOYEE):
        response = await client.get("/api/v1/admin/security/ip-rules")

    assert response.status_code == 403


async def test_admin_can_list_rules_with_pagination() -> None:
    service = FakeService()
    service.rules = FakeRules([make_rule(), make_rule(cidr="2001:db8::/32")])
    async for client in security_client(service, profile=ADMIN):
        response = await client.get("/api/v1/admin/security/ip-rules?offset=1&limit=1")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["cidr"] == "2001:db8::/32"


@pytest.mark.parametrize(
    ("supplied", "normalized"),
    [("192.0.2.9/24", "192.0.2.0/24"), ("2001:db8::9/64", "2001:db8::/64")],
)
async def test_admin_creates_normalized_ipv4_and_ipv6_rule(supplied: str, normalized: str) -> None:
    service = FakeService()
    async for client in security_client(service, profile=ADMIN):
        response = await client.post(
            "/api/v1/admin/security/ip-rules",
            json={"cidr": supplied, "label": "Office"},
        )

    assert response.status_code == 201
    assert response.json()["cidr"] == normalized
    assert service.create_rule.await_args is not None
    assert service.create_rule.await_args.kwargs["cidr"] == normalized


async def test_admin_api_rejects_malformed_cidr() -> None:
    async for client in security_client(FakeService(), profile=ADMIN):
        response = await client.post(
            "/api/v1/admin/security/ip-rules",
            json={"cidr": "not-a-network", "label": "Invalid"},
        )

    assert response.status_code == 422


async def test_duplicate_rule_returns_conflict() -> None:
    service = FakeService()
    service.create_rule.side_effect = ApplicationError(
        "CONFLICT", "An IP rule for this network already exists.", 409
    )
    async for client in security_client(service, profile=ADMIN):
        response = await client.post(
            "/api/v1/admin/security/ip-rules",
            json={"cidr": "192.0.2.0/24", "label": "Duplicate"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_admin_updates_disables_and_deletes_rule() -> None:
    service = FakeService()
    rule_id = uuid4()
    async for client in security_client(service, profile=ADMIN):
        updated = await client.patch(
            f"/api/v1/admin/security/ip-rules/{rule_id}", json={"label": "Updated"}
        )
        disabled = await client.patch(
            f"/api/v1/admin/security/ip-rules/{rule_id}", json={"enabled": False}
        )
        deleted = await client.delete(f"/api/v1/admin/security/ip-rules/{rule_id}")

    assert updated.status_code == 200
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204


async def test_current_ip_uses_resolved_socket_peer() -> None:
    async for client in security_client(FakeService(), profile=ADMIN, client_ip="2001:db8::8"):
        response = await client.get("/api/v1/admin/security/ip/current")

    assert response.status_code == 200
    assert response.json() == {"ip": "2001:db8::8", "emergency_bypass": False}


async def test_audit_pagination_omits_metadata() -> None:
    service = FakeService()
    service.audits = FakeAudits(
        [
            SecurityAuditEvent(
                id=uuid4(),
                actor_user_id=ADMIN.id,
                event_type=SecurityAuditEventType.IP_RULE_CREATED,
                request_ip="192.0.2.9",
                user_agent="test-agent",
                resource_type="ip_access_rule",
                resource_id=uuid4(),
                event_metadata={"authorization": "must-not-leak"},
                created_at=datetime.now(UTC),
            )
        ]
    )
    async for client in security_client(service, profile=ADMIN):
        response = await client.get("/api/v1/admin/security/audit-events?offset=0&limit=10")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "metadata" not in response.json()["items"][0]


async def test_phase4_routes_appear_in_openapi() -> None:
    async for client in security_client(FakeService(), profile=ADMIN):
        schema = (await client.get("/openapi.json")).json()

    assert "/api/v1/admin/security/ip/current" in schema["paths"]
    assert "/api/v1/admin/security/ip-rules" in schema["paths"]
    assert "/api/v1/admin/security/ip-rules/{rule_id}" in schema["paths"]
    assert "/api/v1/admin/security/audit-events" in schema["paths"]
