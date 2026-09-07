"""
HireAndTech FastAPI application factory.

Purpose:
    Assemble the HTTP application and its cross-cutting infrastructure.

Responsibilities:
    - Load and validate runtime configuration.
    - Configure structured application logging.
    - Register middleware, error handlers, and versioned API routes.

Does NOT:
    - Establish database or queue connections.
    - Implement authentication or business-domain behavior.

Security:
    API documentation is disabled outside local and test environments. Host and
    CORS policies are explicit configuration rather than permissive defaults.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with validated, injectable settings."""
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)

    expose_docs = application_settings.environment in {"local", "test"}
    application = FastAPI(
        title=application_settings.application_name,
        version=__version__,
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    application.state.settings = application_settings

    application.add_middleware(
        CORSMiddleware,
        allow_origins=application_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=application_settings.allowed_hosts,
    )
    application.add_middleware(RequestContextMiddleware)

    register_exception_handlers(application)
    application.include_router(v1_router, prefix=application_settings.api_v1_prefix)
    return application


app = create_app()
