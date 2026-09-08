"""Typed identity claims produced only after JWT verification succeeds."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedClaims:
    """Trusted identity attributes from a cryptographically verified access token."""

    subject: UUID
    email: str | None = None
    session_id: UUID | str | None = None
    provider_role: str | None = None
