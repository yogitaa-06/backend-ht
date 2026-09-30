"""Tests for honest, idempotent async-search execution state."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.resumes import CandidateProfile
from app.domain.search import JobSearch
from app.jobs.types import SearchStatus
from app.search.execution import SearchExecutionService


@pytest.mark.anyio
async def test_search_execution_no_profile_fails() -> None:
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.QUEUED, progress=0)
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search

    profile_repository = AsyncMock()
    profile_repository.get_latest_owned.return_value = None

    session = AsyncMock()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    await SearchExecutionService(
        repository=repository, profile_repository=profile_repository, clock=lambda: now
    ).execute(session, search.id)

    assert search.status is SearchStatus.FAILED
    assert search.current_stage == "loading_profile_failed"
    assert search.progress == 0
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_search_execution_succeeds() -> None:
    search = JobSearch(
        id=uuid4(), user_id=uuid4(), status=SearchStatus.QUEUED, progress=0, requested_limit=10
    )
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search

    profile_repository = AsyncMock()
    profile_repository.get_latest_owned.return_value = CandidateProfile(
        skills=["Python"],
        years_of_experience=5,
    )

    job_repository = AsyncMock()
    job_repository.search.return_value = ([], 0)

    session = AsyncMock()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    await SearchExecutionService(
        repository=repository,
        profile_repository=profile_repository,
        job_repository=job_repository,
        clock=lambda: now,
    ).execute(session, search.id)

    assert search.status is SearchStatus.COMPLETED
    assert search.current_stage == "completed"
    assert search.progress == 100
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


@pytest.mark.anyio
async def test_search_execution_zero_results_is_completed() -> None:
    search = JobSearch(
        id=uuid4(), user_id=uuid4(), status=SearchStatus.QUEUED, progress=0, requested_limit=10
    )
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search

    profile_repository = AsyncMock()
    profile_repository.get_latest_owned.return_value = CandidateProfile(
        skills=["Python"],
        years_of_experience=5,
    )

    job_repository = AsyncMock()
    # Return zero results
    job_repository.search.return_value = ([], 0)

    session = AsyncMock()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    await SearchExecutionService(
        repository=repository,
        profile_repository=profile_repository,
        job_repository=job_repository,
        clock=lambda: now,
    ).execute(session, search.id)

    assert search.status is SearchStatus.COMPLETED
    assert search.current_stage == "completed"
    assert search.progress == 100
    repository.save_results.assert_awaited_once_with(session, [])
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_search_execution_unexpected_failure_persists_failed_state() -> None:
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.QUEUED, progress=0)
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search

    profile_repository = AsyncMock()
    profile_repository.get_latest_owned.side_effect = RuntimeError("Database boom")

    session = AsyncMock()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    await SearchExecutionService(
        repository=repository, profile_repository=profile_repository, clock=lambda: now
    ).execute(session, search.id)

    assert search.status is SearchStatus.FAILED
    assert search.current_stage == "failed"
    assert "unexpected error" in str(search.error_message)
    session.rollback.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_search_execution_clears_previous_results_on_retry() -> None:
    search = JobSearch(
        id=uuid4(), user_id=uuid4(), status=SearchStatus.QUEUED, progress=0, requested_limit=10
    )
    repository = AsyncMock()
    repository.get_search_for_worker.return_value = search

    profile_repository = AsyncMock()
    profile_repository.get_latest_owned.return_value = CandidateProfile(
        skills=["Python"], years_of_experience=5
    )

    job_repository = AsyncMock()
    job_repository.search.return_value = ([], 0)

    session = AsyncMock()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    await SearchExecutionService(
        repository=repository,
        profile_repository=profile_repository,
        job_repository=job_repository,
        clock=lambda: now,
    ).execute(session, search.id)

    # Must clear existing results before saving new ones
    repository.clear_results.assert_awaited_once_with(session, search.id)
    repository.save_results.assert_awaited_once_with(session, [])
