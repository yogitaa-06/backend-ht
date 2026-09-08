"""Local user profiles that own HireAndTech authorization state."""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base, IdentityTimestampMixin


class ProfileRole(StrEnum):
    """Application roles; these are never sourced from provider JWT role claims."""

    EMPLOYEE = "employee"
    ADMIN = "admin"


class Profile(IdentityTimestampMixin, Base):
    """Administrator-provisioned local authorization profile."""

    __tablename__ = "profiles"

    auth_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    role: Mapped[ProfileRole] = mapped_column(
        Enum(
            ProfileRole,
            name="profile_role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda roles: [role.value for role in roles],
        ),
        nullable=False,
        default=ProfileRole.EMPLOYEE,
        server_default=ProfileRole.EMPLOYEE.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    @validates("email")
    def normalize_email(self, _: str, value: str) -> str:
        """Store a stable representation for uniqueness and safe display."""
        normalized = value.strip().casefold()
        if not normalized or len(normalized) > 320:
            raise ValueError("email must contain between 1 and 320 characters")
        return normalized
