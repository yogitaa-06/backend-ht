"""Hard eligibility rules applied before ranking."""

from decimal import Decimal

from app.jobs.ingestion.normalization import roles_compatible
from app.jobs.matching.models import Candidate, MatchableJob


def experience_compatible(
    candidate_years: Decimal | float | None,
    minimum: int | None,
) -> bool:
    """Return whether the candidate satisfies the minimum experience."""
    return candidate_years is None or minimum is None or float(candidate_years) >= minimum


def is_eligible(candidate: Candidate, job: MatchableJob) -> bool:
    """Reject inactive, role-incompatible, and over-level openings."""
    return (
        job.is_active
        and roles_compatible(candidate.role, job.role_family)
        and experience_compatible(candidate.years_experience, job.experience_min_years)
    )
