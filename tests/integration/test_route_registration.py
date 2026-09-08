"""Regression coverage for nested v1 router registration and HTTP dispatch."""

import pytest
from fastapi.routing import iter_route_contexts
from httpx2 import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.parametrize("prefix", ["/api/v1", "/internal/v1"])
def test_v1_routes_are_registered_before_startup(test_settings: Settings, prefix: str) -> None:
    application = create_app(test_settings.model_copy(update={"api_v1_prefix": prefix}))

    # FastAPI includes routers lazily; inspect resolved paths, including include prefixes.
    registered_routes = {
        (route.path, method)
        for route in iter_route_contexts(application.routes)
        for method in route.methods or ()
    }
    paths = application.openapi()["paths"]

    assert ("/", "GET") in registered_routes
    assert "get" in paths["/"]
    assert not paths["/"]["get"].get("security")
    assert str(application.url_path_for("get_root")) == "/"

    for suffix, name in [
        ("/auth/me", "get_me"),
        ("/health", "health"),
        ("/health/ready", "readiness"),
    ]:
        path = f"{prefix}{suffix}"
        assert (path, "GET") in registered_routes
        assert "get" in paths[path]
        assert str(application.url_path_for(name)) == path


@pytest.mark.anyio
@pytest.mark.parametrize("prefix", ["/api/v1", "/internal/v1"])
async def test_v1_routes_dispatch_with_configured_prefix(
    test_settings: Settings, prefix: str
) -> None:
    application = create_app(test_settings.model_copy(update={"api_v1_prefix": prefix}))
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = await client.get("/")
        health = await client.get(f"{prefix}/health")
        me = await client.get(f"{prefix}/auth/me")

    assert root.status_code == 200
    assert root.json()["health"] == f"{prefix}/health"
    assert health.status_code == 200
    assert health.json()["service"] == "hireandtech-api"
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "UNAUTHENTICATED"
    assert me.headers["WWW-Authenticate"] == "Bearer"
