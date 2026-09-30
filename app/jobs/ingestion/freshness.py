"""Freshness rules shared by ingestion paths."""

from datetime import datetime

from app.domain.jobs import CanonicalJob


def mark_canonical_seen(job: CanonicalJob, observed_at: datetime) -> None:
    """Reactivate a canonical opening observed by an authoritative source."""
    job.last_seen_at = observed_at
    job.is_active = True
