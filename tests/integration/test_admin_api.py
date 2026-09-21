"""Capability and authorization checks for the current administrator API."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import require_admin
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.profiles import Profile, ProfileRole
from app.main import create_app

pytestmark = pytest.mark.anyio


async def _client(profile: Profile | None) -> AsyncIterator[AsyncClient]:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            allowed_hosts=["testserver"],
            cors_allowed_origins=["http://testserver"],
            rate_limit_enabled=False,
        )
    )
    if profile is not None:
        if profile.role is ProfileRole.ADMIN:
            application.dependency_overrides[require_admin] = lambda: profile
        else:

            async def reject() -> Profile:
                raise ApplicationError("FORBIDDEN", "Access is not permitted.", 403)

            application.dependency_overrides[require_admin] = reject
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_admin_route_requires_authentication() -> None:
    async for client in _client(None):
        response = await client.get("/api/v1/admin/settings")

    assert response.status_code == 401


async def test_admin_route_rejects_non_admin() -> None:
    employee = Profile(id=uuid4(), auth_user_id=uuid4(), email="employee-admin-test@example.com")
    async for client in _client(employee):
        response = await client.get("/api/v1/admin/settings")

    assert response.status_code == 403


async def test_admin_route_exposes_safe_settings_and_unsupported_capabilities() -> None:
    administrator = Profile(
        id=uuid4(),
        auth_user_id=uuid4(),
        email="admin-admin-test@example.com",
        role=ProfileRole.ADMIN,
    )
    async for client in _client(administrator):
        settings = await client.get("/api/v1/admin/settings")
        jobs = await client.get("/api/v1/admin/jobs")
        schema = (await client.get("/openapi.json")).json()

    assert settings.status_code == 200
    assert "DATABASE_URL" not in settings.text
    assert jobs.status_code == 501
    assert "/api/v1/admin/dashboard" in schema["paths"]
    assert "/api/v1/admin/resumes" in schema["paths"]
