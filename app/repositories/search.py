"""Data access for async job searches."""

from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.search import JobSearch, JobSearchResult


class SearchRepository:
    """Repository for managing async search state and results."""

    async def create_search(self, session: AsyncSession, search: JobSearch) -> JobSearch:
        """Create a new async search record."""
        session.add(search)
        await session.flush()
        return search

    async def get_search(
        self, session: AsyncSession, search_id: UUID, user_id: UUID
    ) -> JobSearch | None:
        """Get a search by ID and verify ownership."""
        stmt = select(JobSearch).where(
            JobSearch.id == search_id, JobSearch.user_id == user_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_search_for_worker(
        self, session: AsyncSession, search_id: UUID
    ) -> JobSearch | None:
        """Get a search by ID for the background worker (ignores user_id)."""
        stmt = select(JobSearch).where(JobSearch.id == search_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_results(
        self, session: AsyncSession, results: list[JobSearchResult]
    ) -> None:
        """Save a batch of search results."""
        if results:
            session.add_all(results)
            await session.flush()

    async def get_results(
        self, session: AsyncSession, search_id: UUID, page: int = 1, page_size: int = 50
    ) -> tuple[Sequence[JobSearchResult], int]:
        """Get paginated search results with the canonical job loaded."""
        
        # Count total
        count_stmt = select(func.count(JobSearchResult.id)).where(
            JobSearchResult.search_id == search_id
        )
        total = await session.scalar(count_stmt) or 0
        
        if total == 0:
            return [], 0

        # Get items
        offset = (page - 1) * page_size
        stmt = (
            select(JobSearchResult)
            .where(JobSearchResult.search_id == search_id)
            .options(selectinload(JobSearchResult.job))
            .order_by(JobSearchResult.rank.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        return result.scalars().all(), total
