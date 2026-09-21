"""Canonical global-job persistence model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityTimestampMixin


class JobSource(StrEnum):
    DICE = "dice"
    LINKEDIN = "linkedin"
    GLASSDOOR = "glassdoor"


class GlobalJob(IdentityTimestampMixin, Base):
    """One normalized job observed from a global source."""

    __tablename__ = "global_jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_job_id", name="uq_global_jobs_source_external_id"),
        CheckConstraint(
            "experience_min_years IS NULL OR experience_min_years >= 0",
            name="global_jobs_min_experience_nonnegative",
        ),
        CheckConstraint(
            "experience_max_years IS NULL OR experience_max_years >= 0",
            name="global_jobs_max_experience_nonnegative",
        ),
        CheckConstraint(
            "experience_max_years IS NULL OR experience_min_years IS NULL "
            "OR experience_max_years >= experience_min_years",
            name="global_jobs_experience_ordered",
        ),
        Index("ix_global_jobs_source_active", "source", "is_active"),
        Index("ix_global_jobs_active_posted", "is_active", "posted_at"),
        Index("ix_global_jobs_role_family_active", "role_family", "is_active"),
        Index("ix_global_jobs_experience", "experience_min_years", "experience_max_years"),
        Index("ix_global_jobs_location", "location"),
    )

    source: Mapped[JobSource] = mapped_column(String(32), nullable=False)
    external_job_id: Mapped[str] = mapped_column(String(512), nullable=False)
    job_title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False)
    role_family: Mapped[str] = mapped_column(String(64), nullable=False)
    company: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500))
    job_url: Mapped[str | None] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(Text)
    salary_text: Mapped[str | None] = mapped_column(String(500))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    remote: Mapped[bool | None] = mapped_column(Boolean)
    skills: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    experience_min_years: Mapped[int | None] = mapped_column(Integer)
    experience_max_years: Mapped[int | None] = mapped_column(Integer)
    experience_text: Mapped[str | None] = mapped_column(String(500))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    content_hash: Mapped[str | None] = mapped_column(String(128))
