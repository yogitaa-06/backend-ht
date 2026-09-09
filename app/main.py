"""
HireAndTech FastAPI application factory.

Purpose:
    Assemble the HTTP application and its cross-cutting infrastructure.

Responsibilities:
    - Load and validate runtime configuration.
    - Configure structured application logging.
    - Register middleware, error handlers, and versioned API routes.

Does NOT:
    - Run migrations or create business tables at startup.
    - Implement business-domain behavior inside the composition layer.

Security:
    API documentation is disabled outside local and test environments. Host and
    CORS policies are explicit configuration rather than permissive defaults.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.root import router as root_router
from app.api.v1.router import router as v1_router
from app.auth.verifier import SupabaseJwtVerifier
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import Database
from app.security.ip import TrustedClientIpResolver
from app.security.middleware import IpSecurityMiddleware
from app.security.rate_limit import BoundedMemoryRateLimitStore, RouteRateLimiter

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with validated, injectable settings."""
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Own database resources and reject startup when connectivity is unavailable."""
        database = Database(application_settings)
        http_client = httpx.AsyncClient()

        application.state.database = database
        application.state.http_client = http_client
        try:
            logger.info(
                "ip_allowlist_enabled"
                if application_settings.ip_allowlist_enabled
                else "ip_allowlist_disabled",
                extra={"operation": "application_startup"},
            )
            if not await database.check_connection():
                raise RuntimeError("Database is unavailable; API startup aborted")
            yield
        finally:
            await http_client.aclose()
            await database.close()
            application.state.http_client = None
            application.state.database = None

    expose_docs = application_settings.environment in {"local", "test"}
    application = FastAPI(
        title=application_settings.application_name,
        version=__version__,
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
        lifespan=lifespan,
    )
    application.state.settings = application_settings
    application.state.supabase_jwt_verifier = SupabaseJwtVerifier(application_settings)
    rate_limit_store = BoundedMemoryRateLimitStore(application_settings.rate_limit_max_keys)
    application.state.rate_limit_store = rate_limit_store

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
    application.add_middleware(
        IpSecurityMiddleware,
        settings=application_settings,
        resolver=TrustedClientIpResolver(application_settings.trusted_proxy_cidrs),
        rate_limiter=RouteRateLimiter(
            rate_limit_store, fail_closed=application_settings.rate_limit_fail_closed
        ),
    )
    application.add_middleware(RequestContextMiddleware)

    register_exception_handlers(application)
    application.include_router(root_router, tags=["system"])
    application.include_router(v1_router, prefix=application_settings.api_v1_prefix)
    return application


app = create_app()
