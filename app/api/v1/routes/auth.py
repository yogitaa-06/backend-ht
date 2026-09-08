"""Authenticated identity endpoints backed by local application profiles."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_profile
from app.domain.profiles import Profile
from app.schemas.auth import CurrentProfileResponse

router = APIRouter(prefix="/auth")


@router.get("/me", response_model=CurrentProfileResponse, summary="Get the current profile")
async def get_me(
    profile: Annotated[Profile, Depends(get_current_profile)],
) -> Profile:
    """Return the active local profile associated with the verified bearer token."""
    return profile
