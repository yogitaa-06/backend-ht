"""Unversioned public API landing endpoint."""

from fastapi import APIRouter, Request

from app.schemas.root import RootResponse

router = APIRouter()


@router.get("/", response_model=RootResponse, summary="Get public API information")
async def get_root(request: Request) -> RootResponse:
    """Return public metadata without probing authentication or infrastructure."""
    return RootResponse(
        name=request.app.title,
        status="running",
        docs=request.app.docs_url,
        health=str(request.app.url_path_for("health")),
    )
