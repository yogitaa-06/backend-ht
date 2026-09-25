"""Canonical global-job persistence models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdentityTimestampMixin


class JobSource(StrEnum):
    """Supported global job providers."""

    DICE = "dice"
    LINKEDIN = "linkedin"
    GLASSDOOR = "glassdoor"
    HIRINGCAFE = "hiringcafe"


class GlobalJob(IdentityTimestampMixin, Base):
    """Legacy normalized job read model.

    This table remains temporarily for compatibility while user-facing reads
    migrate to the canonical ``jobs`` / ``companies`` / ``job_sources`` graph.

    New architecture should treat CanonicalJob and JobSourceObservation as the
    long-term source of truth.
    """

    __tablename__ = "global_jobs"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_job_id",
            name="uq_global_jobs_source_external_id",
        ),
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
        Index(
            "ix_global_jobs_source_active",
            "source",
            "is_active",
        ),
        Index(
            "ix_global_jobs_active_posted",
            "is_active",
            "posted_at",
        ),
        Index(
            "ix_global_jobs_role_family_active",
            "role_family",
            "is_active",
        ),
        Index(
            "ix_global_jobs_experience",
            "experience_min_years",
            "experience_max_years",
        ),
        Index(
            "ix_global_jobs_location",
            "location",
        ),
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
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    experience_min_years: Mapped[int | None] = mapped_column(Integer)
    experience_max_years: Mapped[int | None] = mapped_column(Integer)
    experience_text: Mapped[str | None] = mapped_column(String(500))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    content_hash: Mapped[str | None] = mapped_column(String(128))


class Company(IdentityTimestampMixin, Base):
    """Conservatively resolved employer shared by canonical openings."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint(
            "normalized_name",
            name="uq_companies_normalized_name",
        ),
        Index(
            "ix_companies_domain",
            "domain",
        ),
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    website_url: Mapped[str | None] = mapped_column(String(2048))
    domain: Mapped[str | None] = mapped_column(String(255))

    jobs: Mapped[list[CanonicalJob]] = relationship(back_populates="company")


class CanonicalJob(IdentityTimestampMixin, Base):
    """One real-world opening independent of any source listing."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "experience_min_years IS NULL OR experience_min_years >= 0",
            name="min_experience_nonnegative",
        ),
        CheckConstraint(
            "experience_max_years IS NULL OR experience_max_years >= 0",
            name="max_experience_nonnegative",
        ),
        CheckConstraint(
            "experience_max_years IS NULL OR experience_min_years IS NULL "
            "OR experience_max_years >= experience_min_years",
            name="experience_ordered",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name="salary_ordered",
        ),
        Index(
            "ix_jobs_company_id",
            "company_id",
        ),
        Index(
            "ix_jobs_canonical_hash",
            "canonical_hash",
        ),
        Index(
            "ix_jobs_normalized_title_location",
            "normalized_title",
            "normalized_location",
        ),
        Index(
            "ix_jobs_active_posted_at",
            "is_active",
            "posted_at",
        ),
        Index(
            "ix_jobs_active_last_seen_at",
            "is_active",
            "last_seen_at",
        ),
        Index(
            "ix_jobs_role_family_active",
            "role_family",
            "is_active",
        ),
    )

    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "companies.id",
            ondelete="RESTRICT",
        )
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(Text)

    location: Mapped[str | None] = mapped_column(String(500))
    normalized_location: Mapped[str | None] = mapped_column(String(500))

    employment_type: Mapped[str | None] = mapped_column(String(100))
    remote_type: Mapped[str | None] = mapped_column(String(32))

    skills: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    experience_min_years: Mapped[int | None] = mapped_column(Integer)
    experience_max_years: Mapped[int | None] = mapped_column(Integer)
    experience_text: Mapped[str | None] = mapped_column(String(500))

    role_family: Mapped[str] = mapped_column(String(64), nullable=False)
    seniority: Mapped[str | None] = mapped_column(String(64))

    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_text: Mapped[str | None] = mapped_column(String(500))

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    canonical_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    company: Mapped[Company | None] = relationship(back_populates="jobs")

    sources: Mapped[list[JobSourceObservation]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class JobSourceObservation(IdentityTimestampMixin, Base):
    """A provider listing pointing to one canonical job."""

    __tablename__ = "job_sources"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_job_id",
            name="uq_job_sources_source_job_id",
        ),
        Index(
            "ix_job_sources_job_id",
            "job_id",
        ),
        Index(
            "ix_job_sources_source_url",
            "source",
            "source_url",
        ),
        Index(
            "ix_job_sources_source_last_seen_at",
            "source",
            "last_seen_at",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "jobs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    source: Mapped[JobSource] = mapped_column(
        String(32),
        nullable=False,
    )

    source_job_id: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    source_url: Mapped[str | None] = mapped_column(String(2048))

    source_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )

    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    job: Mapped[CanonicalJob] = relationship(back_populates="sources")
