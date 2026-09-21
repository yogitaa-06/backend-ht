import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.resumes.dependencies import (
    get_application_settings,
    get_http_client,
    get_resume_parse_executor,
    get_resume_service,
)
from app.resumes.execution import InlineResumeParseExecutor
from app.resumes.parser import DeterministicPdfResumeParser
from app.resumes.storage import SupabaseResumeStorage


def make_request(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        supabase_url="https://example.supabase.co",
        supabase_secret_key=SecretStr("server-only-secret"),
    )


def test_get_application_settings_returns_app_owned_settings() -> None:
    app = FastAPI()
    settings = make_settings()
    app.state.settings = settings

    assert get_application_settings(make_request(app)) is settings


def test_get_application_settings_rejects_missing_state() -> None:
    app = FastAPI()

    with pytest.raises(RuntimeError, match="application settings unavailable"):
        get_application_settings(make_request(app))


@pytest.mark.anyio
async def test_get_http_client_returns_shared_application_client() -> None:
    app = FastAPI()

    async with httpx.AsyncClient() as client:
        app.state.http_client = client

        assert get_http_client(make_request(app)) is client


def test_get_http_client_fails_closed_when_client_is_missing() -> None:
    app = FastAPI()

    with pytest.raises(ApplicationError) as exc_info:
        get_http_client(make_request(app))

    assert exc_info.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert exc_info.value.status_code == 503


@pytest.mark.anyio
async def test_get_resume_service_composes_storage_and_parser() -> None:
    settings = make_settings()
    executor = InlineResumeParseExecutor()

    async with httpx.AsyncClient() as client:
        service = get_resume_service(settings, client, executor)

    assert isinstance(service.storage, SupabaseResumeStorage)
    assert isinstance(service.parser, DeterministicPdfResumeParser)
    assert service.settings is settings
    assert service.parse_executor is executor


@pytest.mark.anyio
async def test_get_resume_service_rejects_missing_supabase_url() -> None:
    settings = make_settings().model_copy(update={"supabase_url": None})
    executor = InlineResumeParseExecutor()

    async with httpx.AsyncClient() as client:
        with pytest.raises(ApplicationError) as exc_info:
            get_resume_service(settings, client, executor)

    assert exc_info.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert exc_info.value.status_code == 503


@pytest.mark.anyio
async def test_get_resume_service_rejects_missing_supabase_secret() -> None:
    settings = make_settings().model_copy(update={"supabase_secret_key": None})
    executor = InlineResumeParseExecutor()

    async with httpx.AsyncClient() as client:
        with pytest.raises(ApplicationError) as exc_info:
            get_resume_service(settings, client, executor)

    assert exc_info.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert exc_info.value.status_code == 503


def test_get_resume_parse_executor_requires_application_state() -> None:
    app = FastAPI()
    with pytest.raises(ApplicationError) as exc_info:
        get_resume_parse_executor(make_request(app))
    assert exc_info.value.code == "RESUME_PARSER_UNAVAILABLE"


def test_get_resume_parse_executor_returns_shared_executor() -> None:
    app = FastAPI()
    executor = InlineResumeParseExecutor()
    app.state.resume_parse_executor = executor
    assert get_resume_parse_executor(make_request(app)) is executor
