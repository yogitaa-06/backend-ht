"""Regression tests for conservative canonical deduplication."""

from datetime import UTC, datetime
from uuid import uuid4

from app.domain.jobs import CanonicalJob
from app.jobs.ingestion.deduplication import ConservativeJobDeduplicator
from app.jobs.ingestion.normalization import NormalizedJob


def test_same_source_url_candidate_can_merge() -> None:
    candidate = CanonicalJob(id=uuid4())

    decision = ConservativeJobDeduplicator().evaluate_same_source_url(candidate)

    assert decision.should_merge is True
    assert decision.canonical_job_id == candidate.id
    assert decision.method == "same_source_url"


def _dummy_incoming() -> NormalizedJob:
    return NormalizedJob(
        source="dice",
        external_job_id="999",
        job_title="Different",
        normalized_title="different",
        role_family="other",
        company="ABC",
        normalized_company="abc",
        location=None,
        normalized_location=None,
        job_url=None,
        description=None,
        salary_text=None,
        employment_type=None,
        remote=None,
        skills=[],
        posted_at=datetime.now(UTC),
        source_updated_at=None,
        experience_min_years=None,
        experience_max_years=None,
        experience_text=None,
        content_hash="abc",
        raw_data={},
    )


def test_cross_source_candidate_never_merges_on_similarity_alone() -> None:
    candidate = CanonicalJob(
        id=uuid4(), is_active=True, company_id=uuid4(), normalized_title="different"
    )

    decision = ConservativeJobDeduplicator().evaluate_cross_source_candidate(
        candidate, _dummy_incoming()
    )

    assert decision.should_merge is False
    assert decision.method == "insufficient_evidence"
