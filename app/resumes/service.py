"""Transactional orchestration for private resume uploads and parsing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus, ResumeStorageCleanup
from app.repositories.resumes import (
    CandidateProfileRepository,
    ResumeRepository,
    ResumeStorageCleanupRepository,
)
from app.resumes.execution import (
    InlineResumeParseExecutor,
    ResumeParseExecutor,
    ResumeParserExecutionError,
)
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
        parse_executor: ResumeParseExecutor | None = None,
        resumes: ResumeRepository | None = None,
        candidate_profiles: CandidateProfileRepository | None = None,
        storage_cleanups: ResumeStorageCleanupRepository | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.parser = parser
        self.parse_executor = parse_executor or InlineResumeParseExecutor()
        self.resumes = resumes or ResumeRepository()
        self.candidate_profiles = candidate_profiles or CandidateProfileRepository()
        self.storage_cleanups = storage_cleanups or ResumeStorageCleanupRepository()

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
        cleanup = await self._reserve_cleanup(session, owner_profile_id, object_key)

        try:
            await self.storage.upload(
                object_key=object_key,
                content=upload.content,
                content_type=upload.content_type,
            )
        except ResumeStorageError as exc:
            await self._clear_cleanup_best_effort(session, cleanup)
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
            parsed = await self.parse_executor.parse(self.parser, upload.content)
        except ApplicationError as exc:
            resume.status = ResumeStatus.PARSE_FAILED
            resume.parse_error_code = exc.code

            try:
                await self.storage_cleanups.remove(session, cleanup)
                await session.flush()
                await session.commit()
            except Exception:
                await session.rollback()
                await self._compensate_with_journal(session, cleanup)
                raise

            raise
        except ResumeParserExecutionError as exc:
            await session.rollback()
            await self._compensate_with_journal(session, cleanup)
            raise _parser_unavailable() from exc

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
            await self.storage_cleanups.remove(session, cleanup)
            await session.flush()
            await session.commit()
        except Exception:
            await session.rollback()
            await self._compensate_with_journal(session, cleanup)
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
        cleanup = await self._reserve_cleanup(
            session,
            owner_profile_id,
            replacement_object_key,
        )

        try:
            await self.storage.upload(
                object_key=replacement_object_key,
                content=upload.content,
                content_type=upload.content_type,
            )
        except ResumeStorageError as exc:
            await self._clear_cleanup_best_effort(session, cleanup)
            raise ApplicationError(
                "RESUME_STORAGE_UNAVAILABLE",
                "The replacement resume could not be stored.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        try:
            parsed = await self.parse_executor.parse(self.parser, upload.content)
        except ApplicationError:
            await self._compensate_with_journal(session, cleanup)
            raise
        except ResumeParserExecutionError as exc:
            await session.rollback()
            await self._compensate_with_journal(session, cleanup)
            raise _parser_unavailable() from exc

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
        old_cleanup = self._cleanup_record(
            owner_profile_id,
            current.storage_object_key,
            available_at=datetime.now(UTC),
        )

        try:
            await self.storage_cleanups.add(session, old_cleanup)
            await self.storage_cleanups.remove(session, cleanup)
            await session.flush()
            await session.commit()
        except StaleDataError as exc:
            await session.rollback()
            await self._compensate_with_journal(session, cleanup)
            raise _concurrent_change() from exc
        except Exception:
            await session.rollback()
            await self._compensate_with_journal(session, cleanup)
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
        await self._clear_cleanup_best_effort(session, old_cleanup)

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
            cleanup = self._cleanup_record(
                owner_profile_id,
                resume.storage_object_key,
                available_at=datetime.now(UTC),
            )

            try:
                await self.storage_cleanups.add(session, cleanup)
                await session.flush()
                await session.commit()
            except StaleDataError as exc:
                await session.rollback()
                raise _concurrent_change() from exc
            except Exception:
                await session.rollback()
                raise
        else:
            existing_cleanup = await self.storage_cleanups.get_by_object_key(
                session,
                object_key=resume.storage_object_key,
            )
            if existing_cleanup is None:
                cleanup = self._cleanup_record(
                    owner_profile_id,
                    resume.storage_object_key,
                    available_at=datetime.now(UTC),
                )
                await self.storage_cleanups.add(session, cleanup)
                await session.flush()
                await session.commit()
            else:
                cleanup = existing_cleanup

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
        await self._clear_cleanup_best_effort(session, cleanup)

        return resume

    async def reconcile_storage_cleanups(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
    ) -> tuple[int, int]:
        """Process a bounded batch of durable cleanup intents."""
        cleanups = await self.storage_cleanups.list_due_for_update(
            session,
            now=datetime.now(UTC),
            limit=limit,
        )
        removed = 0
        failed = 0
        for cleanup in cleanups:
            try:
                await self.storage.delete(object_key=cleanup.storage_object_key)
            except ResumeStorageError:
                cleanup.attempts += 1
                cleanup.last_error_code = "RESUME_STORAGE_UNAVAILABLE"
                failed += 1
            else:
                await self.storage_cleanups.remove(session, cleanup)
                removed += 1
        await session.commit()
        return removed, failed

    async def _reserve_cleanup(
        self,
        session: AsyncSession,
        owner_profile_id: UUID,
        object_key: str,
    ) -> ResumeStorageCleanup:
        cleanup = self._cleanup_record(
            owner_profile_id,
            object_key,
            available_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        await self.storage_cleanups.add(session, cleanup)
        try:
            await session.flush()
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return cleanup

    def _cleanup_record(
        self,
        owner_profile_id: UUID,
        object_key: str,
        *,
        available_at: datetime,
    ) -> ResumeStorageCleanup:
        return ResumeStorageCleanup(
            owner_profile_id=owner_profile_id,
            storage_bucket=self.settings.resume_storage_bucket,
            storage_object_key=object_key,
            available_at=available_at,
            attempts=0,
            last_error_code=None,
        )

    async def _compensate_with_journal(
        self,
        session: AsyncSession,
        cleanup: ResumeStorageCleanup,
    ) -> None:
        """Best-effort cleanup while retaining the durable intent on failure."""

        try:
            await self.storage.delete(object_key=cleanup.storage_object_key)
        except ResumeStorageError:
            return
        await self._clear_cleanup_best_effort(session, cleanup)

    async def _clear_cleanup_best_effort(
        self,
        session: AsyncSession,
        cleanup: ResumeStorageCleanup,
    ) -> None:
        try:
            await self.storage_cleanups.remove(session, cleanup)
            await session.commit()
        except Exception:
            await session.rollback()


def _parser_unavailable() -> ApplicationError:
    return ApplicationError(
        "RESUME_PARSER_UNAVAILABLE",
        "Resume parsing is temporarily unavailable.",
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _concurrent_change() -> ApplicationError:
    return ApplicationError(
        "CONFLICT",
        "The resume changed during this request. Retry with the latest state.",
        status.HTTP_409_CONFLICT,
    )
