"""Top-level router for version 1 of the public API."""

from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router

router = APIRouter()
router.include_router(auth_router, tags=["authentication"])
router.include_router(health_router, tags=["health"])
