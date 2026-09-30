"""Tests for honest, idempotent async-search execution state."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.search import JobSearch
from app.jobs.types import SearchStatus
from app.search.execution import SearchExecutionService


@pytest.mark.anyio
async def test_unimplemented_execution_is_reported_as_failed() -> None:
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.QUEUED, progress=0)
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search
    session = AsyncMock()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    await SearchExecutionService(repository, clock=lambda: now).execute(session, search.id)

    assert search.status is SearchStatus.FAILED
    assert search.current_stage == "candidate_retrieval_not_implemented"
    assert search.progress == 0
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_terminal_search_is_idempotently_skipped() -> None:
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.FAILED)
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search
    session = AsyncMock()

    await SearchExecutionService(repository).execute(session, search.id)

    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()
