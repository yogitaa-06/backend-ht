"""Database access for local authorization profiles."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.profiles import Profile


class ProfileRepository:
    """Read profiles without embedding authentication or authorization policy."""

    async def get_by_auth_user_id(
        self,
        session: AsyncSession,
        auth_user_id: UUID,
    ) -> Profile | None:
        result = await session.execute(select(Profile).where(Profile.auth_user_id == auth_user_id))
        return result.scalar_one_or_none()
