from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.errors import InfrastructureError
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
