"""Behavior tests for typed deterministic scoring."""

from datetime import UTC, datetime
from uuid import uuid4

from app.domain.jobs import GlobalJob
from app.jobs.matching import Candidate, score_job


def test_score_exposes_typed_components() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    job = GlobalJob(
        id=uuid4(),
        role_family="backend",
        experience_min_years=2,
        skills=["Python", "PostgreSQL"],
        location="Remote",
        remote=True,
        posted_at=now,
        last_seen_at=now,
        is_active=True,
    )
    candidate = Candidate(
        "Backend Engineer",
        3,
        frozenset({"python"}),
        remote_preferred=True,
    )

    score = score_job(candidate, job, now=now)

    assert score.role_score == 30
    assert score.skills_score == 15
    assert score.experience_score == 20
    assert score.location_score == 10
    assert score.freshness_score == 10
    assert score.overall_score == 85
