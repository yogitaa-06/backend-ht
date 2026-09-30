"""Canonical values shared across the jobs, search, and queue domains."""

from enum import StrEnum


class RemoteType(StrEnum):
    """Supported workplace arrangements."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"


class EmploymentType(StrEnum):
    """Normalized employment commitments emitted by ingestion."""

    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"


class SearchStatus(StrEnum):
    """Lifecycle states for an asynchronous job search."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
