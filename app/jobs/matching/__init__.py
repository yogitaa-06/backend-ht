"""Public deterministic matching API."""

from app.jobs.matching.eligibility import experience_compatible, is_eligible
from app.jobs.matching.models import Candidate, JobMatchScore, MatchableJob
from app.jobs.matching.ranking import rank_matches
from app.jobs.matching.scoring import score_job


def rank_job(candidate: Candidate, job: MatchableJob) -> dict[str, float]:
    """Compatibility adapter for the existing recommendation response shape."""
    return score_job(candidate, job).as_legacy_mapping()


__all__ = [
    "Candidate",
    "JobMatchScore",
    "MatchableJob",
    "experience_compatible",
    "is_eligible",
    "rank_job",
    "rank_matches",
    "score_job",
]
