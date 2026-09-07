"""
Process health endpoint.

The endpoint is intentionally dependency-free: it reports whether the API process
can serve requests. Readiness checks for Postgres, Redis, and workers belong in the
phases that introduce those dependencies.
"""

from fastapi import APIRouter

from app import __version__
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Check API process health")
async def health() -> HealthResponse:
    """Return a stable liveness response without leaking infrastructure details."""
    return HealthResponse(status="ok", service="hireandtech-api", version=__version__)
