"""FastAPI dependency wiring for private resume management."""

from typing import Annotated

import httpx
from fastapi import Depends, Request, status

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.resumes.execution import ResumeParseExecutor
from app.resumes.parser import DeterministicPdfResumeParser
from app.resumes.service import ResumeService
from app.resumes.storage import SupabaseResumeStorage


def get_application_settings(request: Request) -> Settings:
    """Resolve validated application settings from app-owned state."""
    settings = getattr(request.app.state, "settings", None)

    if not isinstance(settings, Settings):  # pragma: no cover - composition contract
        raise RuntimeError("application settings unavailable")

    return settings


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Resolve the lifespan-owned shared outbound HTTP client."""
    client = getattr(request.app.state, "http_client", None)

    if not isinstance(client, httpx.AsyncClient):
        raise ApplicationError(
            "RESUME_STORAGE_UNAVAILABLE",
            "Resume storage is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return client


def get_resume_parse_executor(request: Request) -> ResumeParseExecutor:
    """Resolve the application-wide bounded parser execution boundary."""
    executor = getattr(request.app.state, "resume_parse_executor", None)
    if not isinstance(executor, ResumeParseExecutor):
        raise ApplicationError(
            "RESUME_PARSER_UNAVAILABLE",
            "Resume parsing is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return executor


def get_resume_service(
    settings: Annotated[Settings, Depends(get_application_settings)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    parse_executor: Annotated[ResumeParseExecutor, Depends(get_resume_parse_executor)],
) -> ResumeService:
    """Compose the resume service from validated application-owned dependencies."""
    supabase_url = settings.supabase_url
    secret = settings.supabase_secret_key

    if supabase_url is None or secret is None:
        raise ApplicationError(
            "RESUME_STORAGE_UNAVAILABLE",
            "Resume storage is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    storage = SupabaseResumeStorage(
        client=client,
        supabase_url=supabase_url,
        secret_key=secret.get_secret_value(),
        bucket=settings.resume_storage_bucket,
    )

    parser = DeterministicPdfResumeParser(settings=settings)

    return ResumeService(
        settings,
        storage=storage,
        parser=parser,
        parse_executor=parse_executor,
    )
