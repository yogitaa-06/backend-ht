"""Public API landing response contract."""

from typing import Literal

from pydantic import BaseModel


class RootResponse(BaseModel):
    """Safe API metadata and relative links to available endpoints."""

    name: str
    status: Literal["running"]
    docs: str | None
    health: str
