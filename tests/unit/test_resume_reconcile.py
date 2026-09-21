"""Operator cleanup reconciliation command wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.resumes.reconcile import reconcile

pytestmark = pytest.mark.anyio


async def test_reconcile_requires_private_storage_configuration() -> None:
    with pytest.raises(ValueError, match="Supabase storage configuration is required"):
        await reconcile(Settings(_env_file=None), limit=1)


async def test_reconcile_owns_resources_and_processes_requested_batch() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr("postgresql://user:password@localhost/test"),
        database_ssl_mode="disable",
        supabase_url="https://example.supabase.co",
        supabase_secret_key=SecretStr("test-only-secret"),
    )
    session = MagicMock(spec=AsyncSession)
    database = MagicMock()

    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    database.sessions = sessions
    database.close = AsyncMock()
    client = MagicMock()
    client.aclose = AsyncMock()
    service = MagicMock()
    service.reconcile_storage_cleanups = AsyncMock(return_value=(2, 1))

    with (
        patch("app.resumes.reconcile.Database", return_value=database),
        patch("app.resumes.reconcile.httpx.AsyncClient", return_value=client),
        patch("app.resumes.reconcile.SupabaseResumeStorage"),
        patch("app.resumes.reconcile.DeterministicPdfResumeParser"),
        patch("app.resumes.reconcile.ResumeService", return_value=service),
    ):
        result = await reconcile(settings, limit=3)

    assert result == (2, 1)
    service.reconcile_storage_cleanups.assert_awaited_once_with(session, limit=3)
    client.aclose.assert_awaited_once()
    database.close.assert_awaited_once()
