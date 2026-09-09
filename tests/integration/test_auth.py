"""HTTP tests for the authenticated current-profile contract."""

from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.claims import VerifiedClaims
from app.auth.dependencies import get_profile_repository, get_supabase_verifier
from app.auth.verifier import InvalidAccessTokenError, SupabaseJwtVerifier
from app.core.config import Settings
from app.db.session import get_session
from app.domain.profiles import Profile, ProfileRole
from app.main import create_app
from app.repositories.profiles import ProfileRepository

pytestmark = pytest.mark.anyio


class FakeVerifier:
    """Model verified identity outcomes without network or live provider calls."""

    async def verify(self, token: str) -> VerifiedClaims:
        if token in {"malformed", "expired"}:
            raise InvalidAccessTokenError
        return VerifiedClaims(subject=AUTH_USER_ID, provider_role="service_role")


class FakeProfileRepository(ProfileRepository):
    def __init__(self, profile: Profile | None) -> None:
        self.profile = profile

    async def get_by_auth_user_id(
        self,
        session: AsyncSession,
        auth_user_id: object,
    ) -> Profile | None:
        return self.profile


AUTH_USER_ID = uuid4()


def make_profile(*, role: ProfileRole, active: bool = True) -> Profile:
    return Profile(
        id=uuid4(),
        auth_user_id=AUTH_USER_ID,
        email="employee@example.com",
        role=role,
        is_active=active,
    )


async def auth_client(
    profile: Profile | None,
) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=["testserver"],
        cors_allowed_origins=["http://testserver"],
        supabase_url="https://example.supabase.co",
    )
    application = create_app(settings)

    async def fake_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    application.dependency_overrides[get_supabase_verifier] = lambda: cast(
        SupabaseJwtVerifier, FakeVerifier()
    )
    application.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(
        profile
    )
    application.dependency_overrides[get_session] = fake_session
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def request_me(profile: Profile | None, token: str | None) -> Response:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async for client in auth_client(profile):
        return await client.get("/api/v1/auth/me", headers=headers)
    raise AssertionError("client fixture did not yield")


@pytest.mark.parametrize("token", [None, "malformed", "expired"])
async def test_auth_me_rejects_missing_or_invalid_credentials(token: str | None) -> None:
    response = await request_me(make_profile(role=ProfileRole.EMPLOYEE), token)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_auth_me_rejects_valid_token_without_local_profile() -> None:
    response = await request_me(None, "valid")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_auth_me_rejects_inactive_profile() -> None:
    response = await request_me(make_profile(role=ProfileRole.ADMIN, active=False), "valid")

    assert response.status_code == 403


@pytest.mark.parametrize("role", [ProfileRole.EMPLOYEE, ProfileRole.ADMIN])
async def test_auth_me_returns_only_safe_active_profile_fields(role: ProfileRole) -> None:
    profile = make_profile(role=role)

    response = await request_me(profile, "valid")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(profile.id),
        "auth_user_id": str(AUTH_USER_ID),
        "email": "employee@example.com",
        "role": role.value,
        "is_active": True,
    }


async def test_provider_role_does_not_override_local_employee_role() -> None:
    response = await request_me(make_profile(role=ProfileRole.EMPLOYEE), "valid")

    assert response.status_code == 200
    assert response.json()["role"] == "employee"
