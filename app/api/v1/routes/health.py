"""
Process liveness and database readiness endpoints.

The endpoint is intentionally dependency-free: it reports whether the API process
can serve requests. Readiness separately checks Postgres with a bounded query.
"""

from fastapi import APIRouter, Request

from app import __version__
from app.core.errors import ApplicationError
from app.db.session import get_database
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Check API process health")
async def health() -> HealthResponse:
    """Return a stable liveness response without leaking infrastructure details."""
    return HealthResponse(status="ok", service="hireandtech-api", version=__version__)


@router.get("/health/ready", response_model=HealthResponse, summary="Check database readiness")
async def readiness(request: Request) -> HealthResponse:
    """Return 503 during a database outage while liveness remains independent."""
    if not await get_database(request).check_connection():
        raise ApplicationError(
            "DATABASE_UNAVAILABLE",
            "The service is temporarily unavailable.",
            503,
        )
    return await health()
