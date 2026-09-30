"""Regression tests for conservative canonical deduplication."""

from uuid import uuid4

from app.domain.jobs import CanonicalJob
from app.jobs.ingestion.deduplication import ConservativeJobDeduplicator


def test_same_source_url_candidate_can_merge() -> None:
    candidate = CanonicalJob(id=uuid4())

    decision = ConservativeJobDeduplicator().evaluate_same_source_url(candidate)

    assert decision.should_merge is True
    assert decision.canonical_job_id == candidate.id
    assert decision.method == "same_source_url"


def test_cross_source_candidate_never_merges_on_similarity_alone() -> None:
    candidate = CanonicalJob(id=uuid4())

    decision = ConservativeJobDeduplicator().evaluate_cross_source_candidate(candidate)

    assert decision.should_merge is False
    assert decision.method == "cross_source_unverified"
