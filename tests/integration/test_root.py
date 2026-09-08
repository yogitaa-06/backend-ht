"""HTTP regression tests for the lightweight public API landing endpoint."""

import pytest
from httpx2 import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_root_returns_only_safe_metadata_without_authentication(client: AsyncClient) -> None:
    # The shared ASGI client has no lifespan database, bearer token, or auth overrides.
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "HireAndTech API",
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("environment", ["local", "test", "staging", "production"])
async def test_root_links_respect_configuration_and_docs_policy(environment: Environment) -> None:
    settings = Settings(
        _env_file=None,
        environment=environment,
        allowed_hosts=["testserver"],
        cors_allowed_origins=["http://testserver"],
        application_name="Public API",
        api_v1_prefix="/internal/v1",
    )
    application = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Public API",
        "status": "running",
        "docs": "/docs" if environment in {"local", "test"} else None,
        "health": "/internal/v1/health",
    }
