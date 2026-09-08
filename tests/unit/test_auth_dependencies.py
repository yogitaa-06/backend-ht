"""Authorization tests for local profile enforcement and admin access."""

from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.claims import VerifiedClaims
from app.auth.dependencies import get_current_profile, require_admin
from app.core.errors import ApplicationError
from app.domain.profiles import Profile, ProfileRole
from app.repositories.profiles import ProfileRepository

pytestmark = pytest.mark.anyio


def make_profile(*, role: ProfileRole, active: bool = True) -> Profile:
    return Profile(
        id=uuid4(),
        auth_user_id=uuid4(),
        email="USER@Example.com",
        role=role,
        is_active=active,
    )


async def current_profile(profile: Profile | None) -> Profile:
    repository = AsyncMock(spec=ProfileRepository)
    repository.get_by_auth_user_id.return_value = profile
    claims = VerifiedClaims(subject=uuid4(), provider_role="service_role")
    return await get_current_profile(
        claims,
        cast(AsyncSession, object()),
        cast(ProfileRepository, repository),
    )


async def test_missing_profile_is_forbidden_without_auto_provisioning() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        await current_profile(None)

    assert exc_info.value.status_code == 403


async def test_inactive_profile_is_forbidden() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        await current_profile(make_profile(role=ProfileRole.ADMIN, active=False))

    assert exc_info.value.status_code == 403


async def test_employee_is_rejected_by_admin_dependency() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        await require_admin(make_profile(role=ProfileRole.EMPLOYEE))

    assert exc_info.value.status_code == 403


async def test_admin_is_accepted_by_admin_dependency() -> None:
    admin = make_profile(role=ProfileRole.ADMIN)

    assert await require_admin(admin) is admin
