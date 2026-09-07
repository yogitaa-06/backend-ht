"""Health endpoint response contract."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Stable, non-sensitive API liveness payload."""

    status: Literal["ok"]
    service: str
    version: str
