"""Public job search and recommendation contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class JobResponse(BaseModel):
    id: UUID
    source: str
    external_job_id: str
    job_title: str
    role_family: str
    company: str | None
    location: str | None
    job_url: str | None
    description: str | None
    salary_text: str | None
    employment_type: str | None
    remote: bool | None
    skills: list[str]
    posted_at: datetime | None
    experience_min_years: int | None
    experience_max_years: int | None
    experience_text: str | None
    match_score: float | None = None
    role_score: float | None = None
    skills_score: float | None = None
    experience_score: float | None = None
    location_score: float | None = None
    freshness_score: float | None = None


class JobPage(BaseModel):
    items: list[JobResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
