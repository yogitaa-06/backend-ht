from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.search import get_search_service, router
from app.auth.dependencies import get_current_profile
from app.db.session import get_session
from app.domain.profiles import Profile
from app.domain.search import JobSearch


@pytest.fixture
def mock_search_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app_client(mock_search_service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    mock_profile = Profile(id=uuid4(), email="test@example.com")

    app.dependency_overrides[get_current_profile] = lambda: mock_profile
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    app.dependency_overrides[get_search_service] = lambda: mock_search_service

    return TestClient(app)


def test_start_search_creates_job_and_returns_202(
    app_client: TestClient, mock_search_service: AsyncMock
) -> None:
    mock_search = JobSearch(id=uuid4(), status="queued")
    mock_search_service.start_search.return_value = mock_search

    payload = {
        "query": "Python Developer",
        "location": "New York",
        "limit": 100,
    }

    response = app_client.post("/api/v1/search", json=payload)

    assert response.status_code == 202
    data = response.json()
    assert "search_id" in data
    assert data["search_id"] == str(mock_search.id)
    assert data["status"] == "queued"
    mock_search_service.start_search.assert_called_once()


def test_get_search_progress_returns_status(
    app_client: TestClient, mock_search_service: AsyncMock
) -> None:
    search_id = uuid4()
    mock_search = JobSearch(
        id=search_id, status="processing", current_stage="processing", progress=10
    )
    mock_search_service.get_search_progress.return_value = mock_search

    response = app_client.get(f"/api/v1/search/{search_id}/progress")
    assert response.status_code == 200
    data = response.json()
    assert data["search_id"] == str(search_id)
    assert data["status"] == "processing"
    assert data["current_stage"] == "processing"
    assert data["progress"] == 10
