"""Background tasks for asynchronous job searching."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.session import Database

logger = logging.getLogger(__name__)


async def run_job_search(ctx: dict[str, Any], search_id: UUID) -> None:
    """
    Perform minimal background search processing for a job search request.
    
    This is the first milestone. It simply transitions the state of the JobSearch
    from 'queued' to 'processing' and finally to 'completed'.
    """
    database: Database = ctx["database"]
    
    try:
        async with database.sessions() as session:
            # Import dynamically to avoid circular dependencies if any
            from sqlalchemy import select

            from app.domain.search import JobSearch
            
            # Load the search record
            stmt = select(JobSearch).where(JobSearch.id == search_id)
            result = await session.execute(stmt)
            search = result.scalar_one_or_none()
            
            if not search:
                logger.warning(
                    "job_search_missing",
                    extra={"search_id": str(search_id)},
                )
                raise RuntimeError("JobSearch not found")
                
            if search.status == "completed":
                logger.info(
                    "job_search_already_completed",
                    extra={"search_id": str(search_id)},
                )
                return
                
            # Transition to processing only if queued
            if search.status == "queued":
                search.status = "processing"
                search.current_stage = "processing"
                search.started_at = datetime.now(UTC)
                await session.commit()
                
                logger.info(
                    "job_search_started",
                    extra={
                        "search_id": str(search_id),
                        "user_id": str(search.user_id),
                    }
                )
            
            # TODO: Future milestones will do real DB filtering and matching here
            
            # Transition to completed
            search.status = "completed"
            search.current_stage = "completed"
            search.progress = 100
            search.completed_at = datetime.now(UTC)
            await session.commit()
            
            duration_ms = 0
            if search.completed_at and search.started_at:
                duration_ms = int((search.completed_at - search.started_at).total_seconds() * 1000)
                
            logger.info(
                "job_search_completed",
                extra={
                    "search_id": str(search_id),
                    "user_id": str(search.user_id),
                    "duration_ms": duration_ms
                }
            )

    except Exception as exc:
        logger.exception(
            "job_search_failed",
            extra={"search_id": str(search_id)},
        )
        # Attempt to record the failure state
        try:
            async with database.sessions() as session:
                stmt = select(JobSearch).where(JobSearch.id == search_id)
                result = await session.execute(stmt)
                search = result.scalar_one_or_none()
                if search:
                    search.status = "failed"
                    search.error_message = "An unexpected error occurred during search processing."
                    await session.commit()
        except Exception as fallback_exc:
            logger.exception(
                "job_search_failure_update_failed",
                extra={"search_id": str(search_id), "fallback_error": str(fallback_exc)},
            )
        raise exc  # Re-raise to trigger ARQ retries if configured
