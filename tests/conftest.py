"""Shared test application and HTTP client fixtures."""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    if os.environ.get("CI") == "true" and not os.environ.get("HIREANDTECH_TEST_DATABASE_URL"):
        pytest.exit("HIREANDTECH_TEST_DATABASE_URL is required in CI but not set.", returncode=1)


@pytest.fixture
def test_settings() -> Settings:
    """Use an explicit test environment rather than developer machine settings."""
    return Settings(
        environment="test",
        allowed_hosts=["testserver"],
        cors_allowed_origins=["http://testserver"],
    )


@pytest.fixture
def anyio_backend() -> str:
    """Run async HTTP tests on the backend used by the production application."""
    return "asyncio"


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    """Create a client that exercises the full middleware and routing stack."""
    transport = ASGITransport(app=create_app(test_settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
