"""Typed, secret-free contracts for the administrator console."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.resumes import ResumeStatus


class AdminPage(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class AdminUserResponse(BaseModel):
    id: UUID
    email: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    resume_count: int
    active_resume_id: UUID | None
    candidate_profile_available: bool
    tracked_job_count: int | None = None
    auto_search_count: int | None = None


class AdminUserPage(AdminPage):
    items: list[AdminUserResponse]


class AdminResumeResponse(BaseModel):
    id: UUID
    user_id: UUID
    user_email: str
    filename: str
    uploaded_at: datetime
    active: bool
    status: ResumeStatus
    parser_version: str | None
    candidate_profile_available: bool


class AdminResumeDetail(AdminResumeResponse):
    model_config = ConfigDict(from_attributes=True)
    full_name: str | None = None
    location: str | None = None
    current_title: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[dict[str, object]] = Field(default_factory=list)
    education: list[dict[str, object]] = Field(default_factory=list)


class AdminResumePage(AdminPage):
    items: list[AdminResumeResponse]


class MetricAvailability(BaseModel):
    status: str
    reason: str | None = None


class DashboardResponse(BaseModel):
    users: dict[str, int]
    resumes: dict[str, int]
    security: dict[str, int]
    jobs: MetricAvailability
    auto_search: MetricAvailability
    ai: MetricAvailability
    system: dict[str, MetricAvailability]


class JobStatsResponse(BaseModel):
    status: str
    reason: str | None = None
    jobs_by_source: dict[str, int] = Field(default_factory=dict)
    jobs_by_role_family: dict[str, int] = Field(default_factory=dict)
    total_jobs: int = 0
    active_jobs: int = 0
    jobs_added_last_24_hours: int = 0


class AnalyticsResponse(BaseModel):
    users_over_time: list[dict[str, object]]
    resume_uploads_over_time: list[dict[str, object]]
    jobs: MetricAvailability
    auto_search: MetricAvailability
    ai: MetricAvailability


class SystemStatusResponse(BaseModel):
    api: MetricAvailability
    database: MetricAvailability
    redis: MetricAvailability
    workers: MetricAvailability
    job_collection: MetricAvailability
    scrapers: dict[str, MetricAvailability]


class AdminSettingsResponse(BaseModel):
    configurable: dict[str, object]
    read_only: dict[str, object]
