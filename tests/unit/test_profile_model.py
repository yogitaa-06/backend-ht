"""Profile mapping and focused repository tests."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.profiles import Profile, ProfileRole
from app.repositories.profiles import ProfileRepository


def test_profile_normalizes_email_and_uses_local_role_values() -> None:
    profile = Profile(auth_user_id=uuid4(), email="  User@Example.COM ")

    assert profile.email == "user@example.com"
    assert {role.value for role in ProfileRole} == {"employee", "admin"}
    assert "password" not in Profile.__table__.columns


def test_profile_constraints_are_declared() -> None:
    table = Profile.__table__

    assert table.schema == "hireandtech"
    assert table.c.auth_user_id.nullable is False
    assert table.c.auth_user_id.unique is True
    assert table.c.email.unique is True
    assert table.c.is_active.nullable is False


@pytest.mark.anyio
async def test_repository_get_by_auth_user_id_returns_profile() -> None:
    expected = Profile(id=uuid4(), auth_user_id=uuid4(), email="user@example.com")
    result = Mock()
    result.scalar_one_or_none.return_value = expected
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result

    actual = await ProfileRepository().get_by_auth_user_id(session, expected.auth_user_id)

    assert actual is expected
    session.execute.assert_awaited_once()
