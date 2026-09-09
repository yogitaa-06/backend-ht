"""Owner-scoped SQLAlchemy access for resumes and candidate profiles."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.resumes import CandidateProfile, Resume, ResumeStatus


class ResumeRepository:
    """Access resume records while requiring authenticated-owner scope."""

    async def add(
        self,
        session: AsyncSession,
        resume: Resume,
    ) -> None:
        """Stage a new resume for persistence."""
        session.add(resume)

    async def get_owned(
        self,
        session: AsyncSession,
        *,
        resume_id: UUID,
        owner_profile_id: UUID,
        include_deleted: bool = False,
    ) -> Resume | None:
        """Return one resume only when it belongs to the supplied owner."""
        statement = select(Resume).where(
            Resume.id == resume_id,
            Resume.owner_profile_id == owner_profile_id,
        )

        if not include_deleted:
            statement = statement.where(Resume.status != ResumeStatus.DELETED)

        result = await session.execute(statement)
        return result.scalar_one_or_none()

    async def get_owned_by_sha256(
        self,
        session: AsyncSession,
        *,
        owner_profile_id: UUID,
        sha256: str,
    ) -> Resume | None:
        """Return an active resume with the same digest for one owner."""
        result = await session.execute(
            select(Resume).where(
                Resume.owner_profile_id == owner_profile_id,
                Resume.sha256 == sha256,
                Resume.status != ResumeStatus.DELETED,
            )
        )
        return result.scalar_one_or_none()

    async def list_owned_page(
        self,
        session: AsyncSession,
        *,
        owner_profile_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[Resume], int]:
        """Return one deterministic page of active resumes for an owner."""
        predicate = (
            Resume.owner_profile_id == owner_profile_id,
            Resume.status != ResumeStatus.DELETED,
        )

        rows = await session.scalars(
            select(Resume)
            .where(*predicate)
            .order_by(Resume.created_at.desc(), Resume.id.desc())
            .offset(offset)
            .limit(limit)
        )

        total = await session.scalar(select(func.count()).select_from(Resume).where(*predicate))

        return list(rows), int(total or 0)


class CandidateProfileRepository:
    """Access parsed candidate profiles through mandatory owner scope."""

    async def add(
        self,
        session: AsyncSession,
        profile: CandidateProfile,
    ) -> None:
        """Stage a candidate profile for persistence."""
        session.add(profile)

    async def get_owned_by_resume_id(
        self,
        session: AsyncSession,
        *,
        resume_id: UUID,
        owner_profile_id: UUID,
    ) -> CandidateProfile | None:
        """Return a candidate profile only for its authenticated owner."""
        result = await session.execute(
            select(CandidateProfile).where(
                CandidateProfile.resume_id == resume_id,
                CandidateProfile.owner_profile_id == owner_profile_id,
            )
        )
        return result.scalar_one_or_none()
