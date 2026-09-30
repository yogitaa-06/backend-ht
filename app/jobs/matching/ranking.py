"""Ordering policy for scored jobs."""

from collections.abc import Iterable

from app.jobs.matching.models import JobMatchScore, MatchableJob


def rank_matches(
    matches: Iterable[tuple[MatchableJob, JobMatchScore]],
) -> list[tuple[MatchableJob, JobMatchScore]]:
    """Order matches by descending score with a stable identity tie-breaker."""
    return sorted(matches, key=lambda item: (-item[1].overall_score, item[0].id))
