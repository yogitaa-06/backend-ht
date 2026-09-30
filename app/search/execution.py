"""Background execution lifecycle for user-specific searches."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.types import SearchStatus
from app.search.repository import SearchRepository

logger = logging.getLogger(__name__)


class SearchExecutionService:
    """Own search state transitions independently from the ARQ entrypoint.

    Candidate retrieval and result persistence are intentionally not represented
    as complete. Until implemented, an accepted search terminates with an explicit
    unsupported stage instead of reporting a fabricated successful result set.
    """

    def __init__(
        self,
        repository: SearchRepository | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository or SearchRepository()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, session: AsyncSession, search_id: UUID) -> None:
        search = await self._repository.get_search_for_worker(session, search_id)
        if search is None:
            logger.warning("job_search_missing", extra={"search_id": str(search_id)})
            return
        if search.status in {SearchStatus.COMPLETED, SearchStatus.FAILED}:
            logger.info(
                "job_search_terminal_state_skipped",
                extra={"search_id": str(search_id), "status": str(search.status)},
            )
            return

        started_at = self._clock()
        search.status = SearchStatus.PROCESSING
        search.current_stage = "candidate_retrieval"
        search.started_at = search.started_at or started_at
        await session.flush()

        search.status = SearchStatus.FAILED
        search.current_stage = "candidate_retrieval_not_implemented"
        search.error_message = "Search execution is not available yet."
        search.completed_at = self._clock()
        await session.commit()
        logger.warning(
            "job_search_execution_not_implemented",
            extra={
                "search_id": str(search_id),
                "user_id": str(search.user_id),
                "duration_ms": int(
                    (search.completed_at - search.started_at).total_seconds() * 1000
                ),
            },
        )
