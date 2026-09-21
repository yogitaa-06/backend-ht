"""Independently runnable ARQ worker configuration."""

from __future__ import annotations

from typing import Any, ClassVar

from arq.cron import cron
from arq.worker import func

from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.jobs.collection import CollectionCoordinator
from app.jobs.locks import RedisCollectionLockManager
from app.jobs.registry import build_collector_registry
from app.queue.client import redis_settings_from_app
from app.queue.scheduler import schedule_due_collections
from app.queue.tasks import run_job_collection

_settings = Settings()


async def startup(ctx: dict[str, Any]) -> None:
    """Build worker-only dependencies and fail clearly when PostgreSQL is unavailable."""
    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    if not await database.check_connection():
        await database.close()
        raise RuntimeError("Database is unavailable; collection worker startup aborted")
    ctx["settings"] = settings
    ctx["database"] = database
    ctx["collector_registry"] = build_collector_registry()
    ctx["collection_coordinator"] = CollectionCoordinator()
    ctx["collection_locks"] = RedisCollectionLockManager(
        ctx["redis"],
        ttl_seconds=settings.job_collection_lock_ttl_seconds,
        namespace=settings.job_collection_redis_namespace,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    """Dispose worker-owned PostgreSQL resources."""
    database = ctx.get("database")
    if isinstance(database, Database):
        await database.close()


class WorkerSettings:
    """Configuration loaded by `arq app.queue.worker.WorkerSettings`."""

    functions: ClassVar[list[Any]] = [
        func(
            run_job_collection,
            max_tries=_settings.job_collection_max_tries,
            timeout=_settings.job_collection_task_timeout_seconds,
            keep_result=3600,
        )
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(
            schedule_due_collections,
            minute=set(range(60)),
            second=0,
            run_at_startup=True,
            unique=True,
            max_tries=1,
        )
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings_from_app(_settings)
    queue_name = _settings.job_collection_queue_name
    health_check_interval = 30
    max_jobs = 10
    log_results = False
