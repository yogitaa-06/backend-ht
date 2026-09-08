"""FastAPI dependencies joining verified identity to local authorization state."""

from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.claims import VerifiedClaims
from app.auth.verifier import (
    InvalidAccessTokenError,
    JwksUnavailableError,
    SupabaseJwtVerifier,
)
from app.core.errors import ApplicationError
from app.db.session import get_session
from app.domain.profiles import Profile, ProfileRole
from app.repositories.profiles import ProfileRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_supabase_verifier(request: Request) -> SupabaseJwtVerifier:
    """Resolve the app-owned verifier so its JWKS cache is shared across requests."""
    verifier = getattr(request.app.state, "supabase_jwt_verifier", None)
    if not isinstance(verifier, SupabaseJwtVerifier):
        raise _authentication_unavailable()
    return verifier


def get_profile_repository() -> ProfileRepository:
    """Provide the focused profile repository for dependency injection."""
    return ProfileRepository()


async def get_verified_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[SupabaseJwtVerifier, Depends(get_supabase_verifier)],
) -> VerifiedClaims:
    """Require a valid bearer token before opening a database session."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthenticated()
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidAccessTokenError:
        raise _unauthenticated() from None
    except JwksUnavailableError:
        raise _authentication_unavailable() from None


async def get_current_profile(
    claims: Annotated[VerifiedClaims, Depends(get_verified_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
    repository: Annotated[ProfileRepository, Depends(get_profile_repository)],
) -> Profile:
    """Load the administrator-provisioned active profile for a verified identity."""
    profile = await repository.get_by_auth_user_id(session, claims.subject)
    if profile is None or not profile.is_active:
        raise ApplicationError("FORBIDDEN", "Access is not permitted.", status.HTTP_403_FORBIDDEN)
    return profile


async def require_admin(
    profile: Annotated[Profile, Depends(get_current_profile)],
) -> Profile:
    """Require the local application role to be admin."""
    if profile.role is not ProfileRole.ADMIN:
        raise ApplicationError("FORBIDDEN", "Access is not permitted.", status.HTTP_403_FORBIDDEN)
    return profile


def _unauthenticated() -> ApplicationError:
    return ApplicationError(
        "UNAUTHENTICATED",
        "Authentication required.",
        status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authentication_unavailable() -> ApplicationError:
    return ApplicationError(
        "AUTHENTICATION_UNAVAILABLE",
        "Authentication is temporarily unavailable.",
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )
