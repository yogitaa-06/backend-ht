"""Tests for stable deterministic match ordering."""

from datetime import UTC, datetime
from uuid import UUID

from app.domain.jobs import GlobalJob
from app.jobs.matching import JobMatchScore, rank_matches


def _job(job_id: str) -> GlobalJob:
    return GlobalJob(
        id=UUID(job_id),
        role_family="backend",
        skills=[],
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        is_active=True,
    )


def _score(value: float) -> JobMatchScore:
    return JobMatchScore(value, 0, 0, 0, 0, 0)


def test_rank_matches_orders_score_then_identity() -> None:
    first = _job("00000000-0000-0000-0000-000000000001")
    second = _job("00000000-0000-0000-0000-000000000002")
    third = _job("00000000-0000-0000-0000-000000000003")

    ranked = rank_matches([(third, _score(80)), (second, _score(90)), (first, _score(90))])

    assert [job.id for job, _ in ranked] == [first.id, second.id, third.id]
