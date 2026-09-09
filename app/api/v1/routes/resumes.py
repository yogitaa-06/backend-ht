"""Authenticated API for private owner-scoped resume management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_profile
from app.core.config import Settings
from app.db.session import get_session
from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile, Resume
from app.resumes.dependencies import get_application_settings, get_resume_service
from app.resumes.service import ResumeService
from app.resumes.validation import ValidatedResumeUpload, validate_resume_upload
from app.schemas.resumes import (
    CandidateProfileResponse,
    ResumeDeleteResponse,
    ResumePage,
    ResumeReplaceResponse,
    ResumeResponse,
)

router = APIRouter(prefix="/resumes")


def _resume_response(resume: Resume) -> ResumeResponse:
    """Convert private persistence state into the safe public resume schema."""
    return ResumeResponse(
        id=resume.id,
        original_filename=resume.original_filename,
        content_type=resume.content_type,
        size_bytes=resume.size_bytes,
        status=resume.status,
        parser_version=resume.parser_version,
        parse_error_code=resume.parse_error_code,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


def _candidate_profile_response(
    profile: CandidateProfile,
) -> CandidateProfileResponse:
    """Convert a persisted candidate profile without exposing private parser data."""
    return CandidateProfileResponse(
        id=profile.id,
        resume_id=profile.resume_id,
        full_name=profile.full_name,
        email=profile.email,
        phone=profile.phone,
        location=profile.location,
        current_title=profile.current_title,
        professional_summary=profile.professional_summary,
        years_of_experience=profile.years_of_experience,
        skills=profile.skills,
        employment_history=profile.employment_history,
        education=profile.education,
        certifications=profile.certifications,
        languages=profile.languages,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def _validated_upload(
    file: UploadFile,
    settings: Settings,
) -> ValidatedResumeUpload:
    """Read only enough bytes to enforce the configured upload-size boundary."""
    try:
        content = await file.read(settings.resume_max_size_bytes + 1)
        return validate_resume_upload(
            filename=file.filename,
            content_type=file.content_type,
            content=content,
            settings=settings,
        )
    finally:
        await file.close()


@router.post(
    "",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_resume(
    file: UploadFile,
    profile: Annotated[Profile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeResponse:
    """Upload, validate, parse once, and persist one private resume."""
    upload = await _validated_upload(file, settings)

    resume = await service.upload(
        session,
        owner_profile_id=profile.id,
        upload=upload,
    )

    return _resume_response(resume)


@router.get("", response_model=ResumePage)
async def list_resumes(
    profile: Annotated[Profile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[ResumeService, Depends(get_resume_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ResumePage:
    """List only active resumes belonging to the authenticated profile."""
    items, total = await service.list_owned(
        session,
        owner_profile_id=profile.id,
        offset=offset,
        limit=limit,
    )

    return ResumePage(
        items=[_resume_response(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{resume_id}/profile",
    response_model=CandidateProfileResponse,
)
async def get_candidate_profile(
    resume_id: UUID,
    profile: Annotated[Profile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> CandidateProfileResponse:
    """Return the structured profile for one owned active resume."""
    candidate_profile = await service.get_candidate_profile(
        session,
        resume_id=resume_id,
        owner_profile_id=profile.id,
    )

    return _candidate_profile_response(candidate_profile)


@router.post(
    "/{resume_id}/replace",
    response_model=ResumeReplaceResponse,
)
async def replace_resume(
    resume_id: UUID,
    file: UploadFile,
    profile: Annotated[Profile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_application_settings)],
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeReplaceResponse:
    """Replace one owned resume with a newly validated and parsed resume."""
    upload = await _validated_upload(file, settings)

    replacement = await service.replace(
        session,
        resume_id=resume_id,
        owner_profile_id=profile.id,
        upload=upload,
    )

    return ResumeReplaceResponse(
        resume=_resume_response(replacement),
        replaced=True,
    )


@router.delete(
    "/{resume_id}",
    response_model=ResumeDeleteResponse,
)
async def delete_resume(
    resume_id: UUID,
    profile: Annotated[Profile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeDeleteResponse:
    """Soft-delete one owned resume and remove its private storage object."""
    resume = await service.delete(
        session,
        resume_id=resume_id,
        owner_profile_id=profile.id,
    )

    return ResumeDeleteResponse(
        resume_id=resume.id,
        deleted=True,
    )
