"""Tests for canonical freshness policy."""

from datetime import UTC, datetime

from app.domain.jobs import CanonicalJob
from app.jobs.ingestion.freshness import mark_canonical_seen


def test_mark_seen_reactivates_job() -> None:
    observed_at = datetime(2026, 1, 2, tzinfo=UTC)
    job = CanonicalJob(is_active=False)

    mark_canonical_seen(job, observed_at)

    assert job.is_active is True
    assert job.last_seen_at == observed_at
