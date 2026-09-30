"""Background tasks for job freshness lifecycle."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.db.session import Database
from app.domain.jobs import JobSource
from app.repositories.canonical_jobs import CanonicalJobRepository

logger = logging.getLogger(__name__)


async def deactivate_stale_jobs_cron(ctx: dict[str, Any]) -> dict[str, int]:
    """Cron task to deactivate stale sources across all supported platforms."""
    settings: Settings = ctx["settings"]
    database: Database = ctx["database"]

    stale_threshold = datetime.now(UTC) - timedelta(hours=settings.job_stale_after_hours)
    safety_window_start = datetime.now(UTC) - timedelta(hours=settings.job_stale_safety_hours)

    repository = CanonicalJobRepository()

    results = {}
    async with database.sessions() as session:
        for source in JobSource:
            try:
                async with session.begin():
                    count = await repository.deactivate_stale_sources(
                        session,
                        source=source.value,
                        stale_threshold=stale_threshold,
                        safety_window_start=safety_window_start,
                    )
                results[source.value] = count
                if count > 0:
                    logger.info(
                        "stale_sources_deactivated",
                        extra={"source": source.value, "count": count},
                    )
            except Exception:
                logger.exception(
                    "stale_source_deactivation_failed",
                    extra={"source": source.value},
                )

    return results
