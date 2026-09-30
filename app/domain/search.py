"""Domain models for asynchronous job search and results."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdentityTimestampMixin
from app.domain.jobs import CanonicalJob
from app.domain.profiles import Profile
from app.jobs.types import RemoteType, SearchStatus


class JobSearch(IdentityTimestampMixin, Base):
    """A record of an asynchronous user search."""

    __tablename__ = "job_searches"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="chk_progress_range"),
        Index("ix_job_searches_user_id", "user_id"),
        Index("ix_job_searches_status", "status"),
        Index("ix_job_searches_created_at", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SearchStatus] = mapped_column(
        String(32), nullable=False, default=SearchStatus.QUEUED
    )

    query: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    remote_type: Mapped[RemoteType | None] = mapped_column(String(32))
    job_type: Mapped[str | None] = mapped_column(String(100))
    experience_min: Mapped[int | None] = mapped_column(Integer)
    experience_max: Mapped[int | None] = mapped_column(Integer)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(String(1024))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[Profile] = relationship()
    results: Mapped[list[JobSearchResult]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )


class JobSearchResult(IdentityTimestampMixin, Base):
    """A single matched job for a specific search."""

    __tablename__ = "job_search_results"
    __table_args__ = (
        UniqueConstraint("search_id", "job_id", name="uq_job_search_results_search_job"),
        Index("ix_job_search_results_search_id", "search_id"),
        Index("ix_job_search_results_rank", "search_id", "rank"),
    )

    search_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_searches.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    skills_score: Mapped[float] = mapped_column(Float, nullable=False)
    experience_score: Mapped[float] = mapped_column(Float, nullable=False)
    location_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)

    search: Mapped[JobSearch] = relationship(back_populates="results")
    job: Mapped[CanonicalJob] = relationship()
