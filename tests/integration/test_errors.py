"""Integration tests for safe and correlatable API error responses."""

import pytest
from fastapi import FastAPI, Query
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app

pytestmark = pytest.mark.anyio


def _error_test_app(settings: Settings) -> FastAPI:
    application = create_app(settings)

    @application.get("/expected-error")
    async def expected_error() -> None:
        raise ApplicationError(code="RESOURCE_CONFLICT", message="The resource already exists.")

    @application.get("/unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError("sensitive database detail")

    @application.get("/validated")
    async def validated(limit: int = Query(ge=1)) -> dict[str, int]:
        return {"limit": limit}

    return application


async def test_expected_application_error_uses_stable_contract(
    test_settings: Settings,
) -> None:
    transport = ASGITransport(app=_error_test_app(test_settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/expected-error", headers={"X-Request-ID": "known-error"})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "RESOURCE_CONFLICT",
            "message": "The resource already exists.",
            "request_id": "known-error",
        }
    }


async def test_validation_error_reports_safe_field_details(test_settings: Settings) -> None:
    transport = ASGITransport(app=_error_test_app(test_settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/validated", params={"limit": 0})

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert body["details"][0]["location"] == ["query", "limit"]


async def test_unexpected_error_hides_exception_detail(test_settings: Settings) -> None:
    transport = ASGITransport(app=_error_test_app(test_settings), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/unexpected-error",
            headers={"X-Request-ID": "unexpected-error"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "unexpected-error"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "request_id": "unexpected-error",
        }
    }
    assert "sensitive database detail" not in response.text


async def test_unknown_route_uses_safe_error_contract(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist", headers={"X-Request-ID": "not-found"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
            "request_id": "not-found",
        }
    }
