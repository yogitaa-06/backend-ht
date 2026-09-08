"""Safe public contracts for authenticated profile information."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.profiles import ProfileRole


class CurrentProfileResponse(BaseModel):
    """Application profile fields safe to return to the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auth_user_id: UUID
    email: str
    role: ProfileRole
    is_active: bool
