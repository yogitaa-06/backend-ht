"""Efficient read-only aggregates used by the administrator console."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus


class AdminRepository:
    async def users_page(
        self, session: AsyncSession, *, page: int, page_size: int, query: str | None
    ) -> tuple[list[Profile], int]:
        predicate = () if not query else (Profile.email.ilike(f"%{query}%"),)
        rows = await session.scalars(
            select(Profile)
            .where(*predicate)
            .order_by(Profile.created_at.desc(), Profile.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        total = await session.scalar(select(func.count()).select_from(Profile).where(*predicate))
        return list(rows), int(total or 0)

    async def user_counts(self, session: AsyncSession) -> dict[str, int]:
        total = await session.scalar(select(func.count()).select_from(Profile))
        admins = await session.scalar(
            select(func.count()).select_from(Profile).where(Profile.role == "admin")
        )
        recent_since = datetime.now(UTC) - timedelta(days=30)
        recent = await session.scalar(
            select(func.count()).select_from(Profile).where(Profile.created_at >= recent_since)
        )
        return {
            "total_users": int(total or 0),
            "admin_users": int(admins or 0),
            "recently_created_users": int(recent or 0),
        }

    async def resume_counts(self, session: AsyncSession) -> dict[str, int]:
        active = Resume.status != ResumeStatus.DELETED
        total = await session.scalar(select(func.count()).select_from(Resume))
        active_count = await session.scalar(select(func.count()).select_from(Resume).where(active))
        owners = await session.scalar(
            select(func.count(func.distinct(Resume.owner_profile_id))).where(active)
        )
        parsed = await session.scalar(select(func.count()).select_from(CandidateProfile))
        return {
            "total_resumes": int(total or 0),
            "active_resumes": int(active_count or 0),
            "users_with_resumes": int(owners or 0),
            "parsed_candidate_profiles": int(parsed or 0),
        }

    async def resumes_page(
        self, session: AsyncSession, *, page: int, page_size: int
    ) -> tuple[list[tuple[Resume, Profile, CandidateProfile | None]], int]:
        stmt = (
            select(Resume, Profile, CandidateProfile)
            .join(Profile, Profile.id == Resume.owner_profile_id)
            .outerjoin(CandidateProfile, CandidateProfile.resume_id == Resume.id)
            .where(Resume.status != ResumeStatus.DELETED)
            .order_by(Resume.created_at.desc(), Resume.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        total = await session.scalar(
            select(func.count()).select_from(Resume).where(Resume.status != ResumeStatus.DELETED)
        )
        rows = [(row[0], row[1], row[2]) for row in result.all()]
        return rows, int(total or 0)

    async def resume(
        self, session: AsyncSession, resume_id: UUID
    ) -> tuple[Resume, Profile, CandidateProfile | None] | None:
        result = await session.execute(
            select(Resume, Profile, CandidateProfile)
            .join(Profile, Profile.id == Resume.owner_profile_id)
            .outerjoin(CandidateProfile, CandidateProfile.resume_id == Resume.id)
            .where(Resume.id == resume_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0], row[1], row[2]

    async def security_count(self, session: AsyncSession) -> int:
        # SecurityAuditEvent is intentionally queried by its table name through the model import
        # in the route, keeping this repository focused on the primary admin aggregates.
        return 0
