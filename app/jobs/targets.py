"""Typed platform-owned global collection targets."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.jobs import JobSource


class CollectionTarget(BaseModel):
    """One source query scheduled for the shared global job pool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: JobSource
    query: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    max_jobs: int = Field(default=100, ge=1, le=1000)

    @field_validator("query", "location")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("collection target text must not be blank")
        return normalized

    @property
    def identity(self) -> str:
        """Stable, non-sensitive identity used by queue jobs and Redis keys."""
        value = f"{self.source.value}\0{self.query.casefold()}\0{(self.location or '').casefold()}"
        return hashlib.sha256(value.encode()).hexdigest()[:24]


DEFAULT_ROLE_QUERIES = (
    "Software Engineer",
    "Backend Engineer",
    "Frontend Engineer",
    "Full Stack Engineer",
    "DevOps Engineer",
    "Site Reliability Engineer",
    "Platform Engineer",
    "Cloud Engineer",
    "Data Engineer",
    "Data Scientist",
    "Machine Learning Engineer",
    "QA Automation Engineer",
    "Security Engineer",
)


def default_collection_targets() -> list[CollectionTarget]:
    """Return initial Dice-ready US role coverage without invoking a source."""
    return [
        CollectionTarget(source=JobSource.DICE, query=query, location="United States")
        for query in DEFAULT_ROLE_QUERIES
    ]
