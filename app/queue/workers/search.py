"""Independently runnable ARQ worker configuration for async search."""

from typing import Any, ClassVar

from arq.worker import func

from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.queue.connection import redis_settings_from_app
from app.queue.tasks.search import run_job_search
from app.search.execution import SearchExecutionService

_settings = Settings()


async def startup(ctx: dict[str, Any]) -> None:
    """Build worker-only dependencies and fail clearly when PostgreSQL is unavailable."""
    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    if not await database.check_connection():
        await database.close()
        raise RuntimeError("Database is unavailable; search worker startup aborted")
    ctx["settings"] = settings
    ctx["database"] = database
    ctx["search_executor"] = SearchExecutionService()


async def shutdown(ctx: dict[str, Any]) -> None:
    """Dispose worker-owned PostgreSQL resources."""
    database = ctx.get("database")
    if isinstance(database, Database):
        await database.close()


class SearchWorkerSettings:
    """Configuration loaded by `arq app.queue.workers.search.SearchWorkerSettings`."""

    functions: ClassVar[list[Any]] = [
        func(
            run_job_search,
            max_tries=3,
            timeout=60,
            keep_result=3600,
        )
    ]
    cron_jobs: ClassVar[list[Any]] = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings_from_app(_settings)
    queue_name = _settings.job_search_queue_name
    health_check_interval = 30
    max_jobs = 20
    log_results = False
