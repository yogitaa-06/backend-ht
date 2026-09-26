from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.jobs import router
from app.auth.dependencies import get_current_profile
from app.db.session import get_session
from app.domain.profiles import Profile
from app.jobs.service import get_job_service
from typing import cast, List


@pytest.fixture
def mock_job_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app_client(mock_job_service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    mock_profile = Profile(id=uuid4(), email="test@example.com")

    app.dependency_overrides[get_current_profile] = lambda: mock_profile
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    app.dependency_overrides[get_job_service] = lambda: mock_job_service

    return TestClient(app)


def test_search_jobs_delegates_to_service(
    app_client: TestClient, mock_job_service: AsyncMock
) -> None:
    mock_job_service.search.return_value = (cast(List[tuple[object, dict[str, float]]], []), 0)

    response = app_client.get("/jobs?query=python&page=1&page_size=20")

    assert response.status_code == 200
    mock_job_service.search.assert_called_once()
    kwargs = mock_job_service.search.call_args.kwargs
    assert kwargs["query"] == "python"
    assert kwargs["page"] == 1
    assert kwargs["page_size"] == 20


def test_recommended_jobs_delegates_to_service(
    app_client: TestClient, mock_job_service: AsyncMock
) -> None:
    mock_job_service.get_recommendations.return_value = (cast(List[tuple[object, dict[str, float]]], []), 0)

    response = app_client.get("/jobs/recommended?page=2&page_size=10")

    assert response.status_code == 200
    mock_job_service.get_recommendations.assert_called_once()
    kwargs = mock_job_service.get_recommendations.call_args.kwargs
    assert "owner_profile_id" in kwargs
    assert kwargs["page"] == 2
    assert kwargs["page_size"] == 10
