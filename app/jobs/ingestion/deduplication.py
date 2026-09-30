"""Conservative canonical-job deduplication decisions."""

from dataclasses import dataclass
from uuid import UUID

from app.domain.jobs import CanonicalJob


@dataclass(frozen=True, slots=True)
class DedupDecision:
    """Explain whether an observed listing may reuse a canonical job."""

    canonical_job_id: UUID | None
    confidence: float
    method: str
    evidence: tuple[str, ...]
    should_merge: bool


class ConservativeJobDeduplicator:
    """Permit only identity-safe merges during the compatibility migration.

    Source URL candidates are already constrained by source in the repository.
    Cross-source title/company similarity is deliberately not treated as proof.
    """

    def evaluate_same_source_url(self, candidate: CanonicalJob | None) -> DedupDecision:
        if candidate is None:
            return DedupDecision(None, 0.0, "no_candidate", (), False)
        return DedupDecision(
            candidate.id,
            1.0,
            "same_source_url",
            ("source", "normalized_source_url"),
            True,
        )

    def evaluate_cross_source_candidate(self, candidate: CanonicalJob) -> DedupDecision:
        """Reject automated cross-source merging until stronger evidence exists."""
        return DedupDecision(
            candidate.id,
            0.0,
            "cross_source_unverified",
            (),
            False,
        )
