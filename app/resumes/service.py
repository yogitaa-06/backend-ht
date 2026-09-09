"""Transactional orchestration for private resume uploads and parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus
from app.repositories.resumes import CandidateProfileRepository, ResumeRepository
from app.resumes.parser import ResumeParser
from app.resumes.storage import (
    ResumeStorage,
    ResumeStorageError,
    build_resume_object_key,
)
from app.resumes.validation import ValidatedResumeUpload


class ResumeService:
    """Own resume upload, parsing, persistence, and compensation invariants."""

    def __init__(
        self,
        settings: Settings,
        *,
        storage: ResumeStorage,
        parser: ResumeParser,
        resumes: ResumeRepository | None = None,
        candidate_profiles: CandidateProfileRepository | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.parser = parser
        self.resumes = resumes or ResumeRepository()
        self.candidate_profiles = candidate_profiles or CandidateProfileRepository()

    async def upload(
        self,
        session: AsyncSession,
        *,
        owner_profile_id: UUID,
        upload: ValidatedResumeUpload,
    ) -> Resume:
        """Store, parse once, and persist one owner-bound resume."""

        resume_id = uuid4()
        object_key = build_resume_object_key(owner_profile_id, resume_id)

        try:
            await self.storage.upload(
                object_key=object_key,
                content=upload.content,
                content_type=upload.content_type,
            )
        except ResumeStorageError as exc:
            raise ApplicationError(
                "RESUME_STORAGE_UNAVAILABLE",
                "The resume could not be stored.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        resume = Resume(
            id=resume_id,
            owner_profile_id=owner_profile_id,
            original_filename=upload.original_filename,
            storage_bucket=self.settings.resume_storage_bucket,
            storage_object_key=object_key,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            status=ResumeStatus.PARSING,
            parser_version=self.settings.resume_parser_version,
            parse_error_code=None,
        )

        await self.resumes.add(session, resume)

        try:
            parsed = self.parser.parse(upload.content)
        except ApplicationError as exc:
            resume.status = ResumeStatus.PARSE_FAILED
            resume.parse_error_code = exc.code

            try:
                await session.flush()
                await session.commit()
            except Exception:
                await session.rollback()
                await self._compensate_storage(object_key)
                raise

            raise

        profile = CandidateProfile(
            resume=resume,
            resume_id=resume.id,
            owner_profile_id=owner_profile_id,
            full_name=parsed.full_name,
            email=parsed.email,
            phone=parsed.phone,
            location=parsed.location,
            current_title=parsed.current_title,
            professional_summary=parsed.professional_summary,
            years_of_experience=parsed.years_of_experience,
            extracted_text=parsed.extracted_text,
            skills=parsed.skills,
            employment_history=[
                entry.model_dump(mode="json") for entry in parsed.employment_history
            ],
            education=[entry.model_dump(mode="json") for entry in parsed.education],
            certifications=parsed.certifications,
            languages=parsed.languages,
            raw_parser_output=parsed.raw_parser_output,
        )

        await self.candidate_profiles.add(session, profile)

        resume.status = ResumeStatus.PARSED
        resume.parse_error_code = None

        try:
            await session.flush()
            await session.commit()
        except Exception:
            await session.rollback()
            await self._compensate_storage(object_key)
            raise

        return resume

    async def replace(
        self,
        session: AsyncSession,
        *,
        resume_id: UUID,
        owner_profile_id: UUID,
        upload: ValidatedResumeUpload,
    ) -> Resume:
        """Replace one owned resume without retiring it prematurely."""

        current = await self.resumes.get_owned(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
        )

        if current is None:
            raise ApplicationError(
                "NOT_FOUND",
                "The requested resource was not found.",
                status.HTTP_404_NOT_FOUND,
            )

        replacement_id = uuid4()
        replacement_object_key = build_resume_object_key(
            owner_profile_id,
            replacement_id,
        )

        try:
            await self.storage.upload(
                object_key=replacement_object_key,
                content=upload.content,
                content_type=upload.content_type,
            )
        except ResumeStorageError as exc:
            raise ApplicationError(
                "RESUME_STORAGE_UNAVAILABLE",
                "The replacement resume could not be stored.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        try:
            parsed = self.parser.parse(upload.content)
        except ApplicationError:
            await self._compensate_storage(replacement_object_key)
            raise

        replacement = Resume(
            id=replacement_id,
            owner_profile_id=owner_profile_id,
            original_filename=upload.original_filename,
            storage_bucket=self.settings.resume_storage_bucket,
            storage_object_key=replacement_object_key,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            status=ResumeStatus.PARSED,
            parser_version=self.settings.resume_parser_version,
            parse_error_code=None,
        )

        profile = CandidateProfile(
            resume=replacement,
            resume_id=replacement.id,
            owner_profile_id=owner_profile_id,
            full_name=parsed.full_name,
            email=parsed.email,
            phone=parsed.phone,
            location=parsed.location,
            current_title=parsed.current_title,
            professional_summary=parsed.professional_summary,
            years_of_experience=parsed.years_of_experience,
            extracted_text=parsed.extracted_text,
            skills=parsed.skills,
            employment_history=[
                entry.model_dump(mode="json") for entry in parsed.employment_history
            ],
            education=[entry.model_dump(mode="json") for entry in parsed.education],
            certifications=parsed.certifications,
            languages=parsed.languages,
            raw_parser_output=parsed.raw_parser_output,
        )

        await self.resumes.add(session, replacement)
        await self.candidate_profiles.add(session, profile)

        current.status = ResumeStatus.DELETED
        current.deleted_at = datetime.now(UTC)

        try:
            await session.flush()
            await session.commit()
        except Exception:
            await session.rollback()
            await self._compensate_storage(replacement_object_key)
            raise

        try:
            await self.storage.delete(
                object_key=current.storage_object_key,
            )
        except ResumeStorageError as exc:
            raise ApplicationError(
                "RESUME_STORAGE_UNAVAILABLE",
                "The replaced resume storage cleanup could not be completed.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        return replacement

    async def list_owned(
        self,
        session: AsyncSession,
        *,
        owner_profile_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[Resume], int]:
        """Return one page of active resumes belonging to the authenticated owner."""
        return await self.resumes.list_owned_page(
            session,
            owner_profile_id=owner_profile_id,
            offset=offset,
            limit=limit,
        )

    async def get_candidate_profile(
        self,
        session: AsyncSession,
        *,
        resume_id: UUID,
        owner_profile_id: UUID,
    ) -> CandidateProfile:
        """Return one parsed candidate profile belonging to the authenticated owner."""
        resume = await self.resumes.get_owned(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
        )

        if resume is None:
            raise ApplicationError(
                "NOT_FOUND",
                "The requested resource was not found.",
                status.HTTP_404_NOT_FOUND,
            )

        profile = await self.candidate_profiles.get_owned_by_resume_id(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
        )

        if profile is None:
            raise ApplicationError(
                "NOT_FOUND",
                "The requested resource was not found.",
                status.HTTP_404_NOT_FOUND,
            )

        return profile

    async def delete(
        self,
        session: AsyncSession,
        *,
        resume_id: UUID,
        owner_profile_id: UUID,
    ) -> Resume:
        """Soft-delete an owned resume and remove its private storage object."""

        resume = await self.resumes.get_owned(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
            include_deleted=True,
        )

        if resume is None:
            raise ApplicationError(
                "NOT_FOUND",
                "The requested resource was not found.",
                status.HTTP_404_NOT_FOUND,
            )

        if resume.status != ResumeStatus.DELETED:
            resume.status = ResumeStatus.DELETED
            resume.deleted_at = datetime.now(UTC)

            try:
                await session.flush()
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        try:
            await self.storage.delete(
                object_key=resume.storage_object_key,
            )
        except ResumeStorageError as exc:
            raise ApplicationError(
                "RESUME_STORAGE_UNAVAILABLE",
                "The resume storage cleanup could not be completed.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        return resume

    async def _compensate_storage(self, object_key: str) -> None:
        """Best-effort cleanup after database persistence fails."""

        try:
            await self.storage.delete(object_key=object_key)
        except ResumeStorageError:
            # Never replace the original database failure with a cleanup failure.
            pass
