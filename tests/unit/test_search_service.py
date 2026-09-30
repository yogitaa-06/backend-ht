from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.errors import ConflictError, InfrastructureError, NotFoundError
from app.domain.search import JobSearch
from app.jobs.types import SearchStatus
from app.schemas.search import AsyncSearchRequest
from app.search.service import SearchService


@pytest.fixture
def mock_repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_settings() -> AsyncMock:
    settings = AsyncMock()
    settings.job_search_queue_name = "test_queue"
    return settings


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def search_service(
    mock_repository: AsyncMock, mock_settings: AsyncMock, mock_redis: AsyncMock
) -> SearchService:
    return SearchService(mock_repository, mock_settings, mock_redis)


@pytest.mark.anyio
async def test_start_search_commits_then_enqueues(
    search_service: SearchService, mock_repository: AsyncMock, mock_redis: AsyncMock
) -> None:
    session = AsyncMock()
    user_id = uuid4()
    request = AsyncSearchRequest(query="Python", location="New York", limit=10)

    # Act
    search = await search_service.start_search(session, user_id, request)

    # Assert
    mock_repository.create_search.assert_called_once()
    assert session.commit.call_count == 1
    mock_redis.enqueue_job.assert_called_once_with(
        "run_job_search",
        search.id,
        _queue_name="test_queue",
    )


@pytest.mark.anyio
async def test_start_search_handles_enqueue_failure(
    search_service: SearchService, mock_repository: AsyncMock, mock_redis: AsyncMock
) -> None:
    session = AsyncMock()
    user_id = uuid4()
    request = AsyncSearchRequest(query="Python", location="New York", limit=10)

    # Simulate enqueue failure
    mock_redis.enqueue_job.side_effect = Exception("Redis offline")

    with pytest.raises(InfrastructureError) as exc_info:
        await search_service.start_search(session, user_id, request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "SEARCH_QUEUE_UNAVAILABLE"

    # The failure state should be committed
    assert session.commit.call_count == 2


@pytest.mark.anyio
async def test_get_search_progress_uses_domain_not_found_error(
    search_service: SearchService, mock_repository: AsyncMock
) -> None:
    mock_repository.get_search.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await search_service.get_search_progress(AsyncMock(), uuid4(), uuid4())

    assert exc_info.value.code == "SEARCH_NOT_FOUND"


@pytest.mark.anyio
async def test_get_search_results_raises_conflict_if_failed(
    search_service: SearchService, mock_repository: AsyncMock
) -> None:
    session = AsyncMock()
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.FAILED)
    mock_repository.get_search.return_value = search

    with pytest.raises(ConflictError) as exc:
        await search_service.get_search_results(session, uuid4(), search.id, 1, 10)
    assert exc.value.code == "SEARCH_FAILED"


@pytest.mark.anyio
async def test_get_search_results_raises_conflict_if_processing(
    search_service: SearchService, mock_repository: AsyncMock
) -> None:
    session = AsyncMock()
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.PROCESSING)
    mock_repository.get_search.return_value = search

    with pytest.raises(ConflictError) as exc:
        await search_service.get_search_results(session, uuid4(), search.id, 1, 10)
    assert exc.value.code == "SEARCH_NOT_COMPLETED"


@pytest.mark.anyio
async def test_get_search_results_maps_properties_correctly(
    search_service: SearchService, mock_repository: AsyncMock
) -> None:
    from datetime import UTC, datetime

    session = AsyncMock()
    search = JobSearch(id=uuid4(), user_id=uuid4(), status=SearchStatus.COMPLETED)
    mock_repository.get_search.return_value = search

    from app.domain.jobs import CanonicalJob, JobSourceObservation
    from app.domain.search import JobSearchResult

    canonical_job = CanonicalJob(
        id=uuid4(),
        title="Software Engineer",
        role_family="engineering",
        description="A great job",
        remote_type="remote",
        skills=["Python"],
    )

    observation = JobSourceObservation(
        source_job_id="ext-123",
        source="dice",
        source_url="http://example.com/job",
        first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        scraped_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    result_row = JobSearchResult(
        search_id=search.id,
        job_id=canonical_job.id,
        rank=1,
        match_score=0.9,
        skills_score=0.9,
        experience_score=0.8,
        location_score=1.0,
        freshness_score=0.5,
    )
    result_row.job = canonical_job

    mock_repository.get_results.return_value = ([result_row], 1)

    # Mock presentation source
    job_repo_mock = AsyncMock()
    job_repo_mock._presentation_source.return_value = observation
    search_service.job_repository = job_repo_mock

    _, items, total = await search_service.get_search_results(
        session, search.user_id, search.id, 1, 10
    )

    assert total == 1
    assert len(items) == 1
    item = items[0]
    assert item.id == canonical_job.id
    assert item.job_title == "Software Engineer"
    assert item.remote is True
    assert item.source == "dice"
    assert item.external_job_id == "ext-123"
    assert item.match_score == 0.9
