"""Integration tests for API liveness and edge security configuration."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_health_endpoint_returns_versioned_contract(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "hireandtech-api",
        "version": "0.1.0",
    }
    assert response.headers["X-Request-ID"]


async def test_valid_caller_request_id_is_correlated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"X-Request-ID": "edge-123"})

    assert response.headers["X-Request-ID"] == "edge-123"


async def test_unsafe_caller_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"X-Request-ID": "unsafe id"})

    assert response.headers["X-Request-ID"] != "unsafe id"


async def test_untrusted_host_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"Host": "attacker.example"})

    assert response.status_code == 400


async def test_cors_preflight_allows_configured_frontend(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://testserver"


async def test_cors_preflight_rejects_unknown_frontend(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers


async def test_production_disables_interactive_api_documentation() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        allowed_hosts=["api.hireandtech.example"],
        cors_allowed_origins=["https://hireandtech.example"],
    )
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(
        transport=transport,
        base_url="https://api.hireandtech.example",
    ) as client:
        docs_response = await client.get("/docs")
        schema_response = await client.get("/openapi.json")

    assert docs_response.status_code == 404
    assert schema_response.status_code == 404
