"""Conservative canonical-job deduplication decisions."""

from dataclasses import dataclass
from uuid import UUID

from app.domain.jobs import CanonicalJob
from app.jobs.ingestion.normalization import NormalizedJob


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

    def evaluate_cross_source_candidate(
        self, candidate: CanonicalJob, incoming: NormalizedJob
    ) -> DedupDecision:
        """Evaluate if an incoming job confidently represents the same real opening."""
        if not candidate.is_active:
            return DedupDecision(candidate.id, 0.0, "candidate_inactive", (), False)

        if candidate.company_id and not incoming.normalized_company:
            return DedupDecision(candidate.id, 0.0, "missing_incoming_company", (), False)

        evidence = []
        confidence = 0.0

        # Company must match conceptually (enforced by candidate selection typically,
        # but check here)
        # We assume the caller already filtered by company_id if possible.

        # 1. Title Similarity
        # For a conservative merge, titles must be very similar or exact normalized matches.
        if candidate.normalized_title == incoming.normalized_title:
            evidence.append("exact_normalized_title")
            confidence += 0.4
        elif (
            candidate.normalized_title in incoming.normalized_title
            or incoming.normalized_title in candidate.normalized_title
        ):
            # Similar but not exact (e.g. 'Software Engineer' vs 'Software Engineer II')
            # Dangerous to merge blindly.
            pass

        # 2. Location Compatibility
        # If both have locations, they should match normalized.
        if candidate.normalized_location and incoming.normalized_location:
            if candidate.normalized_location == incoming.normalized_location:
                evidence.append("exact_normalized_location")
                confidence += 0.2
            else:
                return DedupDecision(candidate.id, 0.0, "location_mismatch", tuple(evidence), False)
        elif not candidate.normalized_location and not incoming.normalized_location:
            evidence.append("both_no_location")
        else:
            # One has location, one does not. Permissive but less confident.
            evidence.append("partial_location")

        # 3. Employment Type
        if candidate.employment_type and incoming.employment_type:
            if candidate.employment_type == incoming.employment_type:
                evidence.append("exact_employment_type")
                confidence += 0.1
            else:
                return DedupDecision(
                    candidate.id, 0.0, "employment_type_mismatch", tuple(evidence), False
                )

        # 4. Description Similarity (Highly supporting)
        # For MVP, we do exact content hash or highly similar.
        if candidate.description and incoming.description:
            # simplistic check for MVP: same hash
            # We can't do heavy NLP here, but we can check if one is a large substring of another
            # or if lengths are very similar and they share a lot of text.
            # But the canonical_hash or content_hash might differ due to source boilerplate.
            desc1 = candidate.description.casefold()
            desc2 = incoming.description.casefold()
            if desc1 == desc2:
                evidence.append("exact_description")
                confidence += 0.5
            elif len(desc1) > 100 and len(desc2) > 100:
                # check if 80% of one is in the other (simplistic)
                if desc1 in desc2 or desc2 in desc1:
                    evidence.append("subset_description")
                    confidence += 0.3
                else:
                    # just basic length/character match? No, too risky.
                    pass

        # 5. Posted Date Proximity
        if candidate.posted_at and incoming.posted_at:
            delta = abs((candidate.posted_at - incoming.posted_at).total_seconds())
            if delta <= 86400 * 3:  # 3 days
                evidence.append("close_posted_date")
                confidence += 0.1

        # Decision Threshold
        # We need high confidence to merge.
        # e.g. Exact title (0.4) + Exact location (0.2) + Description subset (0.3) = 0.9
        if confidence >= 0.7 and "exact_normalized_title" in evidence:
            return DedupDecision(
                candidate.id, confidence, "composite_high_confidence", tuple(evidence), True
            )

        return DedupDecision(
            candidate.id,
            confidence,
            "insufficient_evidence",
            tuple(evidence),
            False,
        )
