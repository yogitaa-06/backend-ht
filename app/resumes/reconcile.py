"""Operator command for retrying durable private-resume storage cleanup intents."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.resumes.parser import DeterministicPdfResumeParser
from app.resumes.service import ResumeService
from app.resumes.storage import SupabaseResumeStorage

logger = logging.getLogger(__name__)


async def reconcile(settings: Settings, *, limit: int = 100) -> tuple[int, int]:
    """Process one bounded batch without exposing provider or database details."""
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        raise ValueError("Supabase storage configuration is required")

    database = Database(settings)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(10, connect=5),
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    )
    storage = SupabaseResumeStorage(
        client=client,
        supabase_url=settings.supabase_url,
        secret_key=settings.supabase_secret_key.get_secret_value(),
        bucket=settings.resume_storage_bucket,
    )
    service = ResumeService(
        settings,
        storage=storage,
        parser=DeterministicPdfResumeParser(settings=settings),
    )
    try:
        async with database.sessions() as session:
            return await service.reconcile_storage_cleanups(session, limit=limit)
    finally:
        await client.aclose()
        await database.close()


def main() -> None:
    """Run one reconciliation batch for a scheduler or controlled operator shell."""
    settings = get_settings()
    configure_logging(settings.log_level)
    removed, failed = asyncio.run(reconcile(settings))
    logger.info(
        "resume_storage_reconciliation_completed",
        extra={"operation": "resume_storage_reconciliation", "removed": removed, "failed": failed},
    )


if __name__ == "__main__":  # pragma: no cover - exercised by the deployment command
    main()
