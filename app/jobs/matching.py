"""Hard eligibility and deterministic ranking for recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from app.jobs.normalization import roles_compatible


@dataclass(frozen=True)
class Candidate:
    """Structured candidate signals used for deterministic matching."""

    role: str
    years_experience: Decimal | float | None
    skills: frozenset[str]
    location: str | None = None
    remote_preferred: bool | None = None


class MatchableJob(Protocol):
    """Minimum job interface required by the matching engine.

    Keeping matching dependent on a protocol rather than a persistence model
    allows the same deterministic logic to work during the migration from the
    legacy ``global_jobs`` read model to canonical jobs.
    """

    @property
    def role_family(self) -> str: ...

    @property
    def experience_min_years(self) -> int | None: ...

    @property
    def skills(self) -> list[str]: ...

    @property
    def location(self) -> str | None: ...

    @property
    def posted_at(self) -> datetime | None: ...

    @property
    def last_seen_at(self) -> datetime: ...

    @property
    def is_active(self) -> bool: ...

    @property
    def remote(self) -> bool | None: ...


def experience_compatible(
    candidate_years: Decimal | float | None,
    minimum: int | None,
) -> bool:
    """Return whether the candidate satisfies the job's minimum experience."""

    return candidate_years is None or minimum is None or float(candidate_years) >= minimum


def is_eligible(candidate: Candidate, job: MatchableJob) -> bool:
    """Apply hard eligibility checks before ranking."""

    return (
        job.is_active
        and roles_compatible(candidate.role, job.role_family)
        and experience_compatible(
            candidate.years_experience,
            job.experience_min_years,
        )
    )


def rank_job(
    candidate: Candidate,
    job: MatchableJob,
) -> dict[str, float]:
    """Return deterministic recommendation component scores.

    Ranking intentionally performs no network calls and no AI requests.
    """

    role_score = 30.0 if roles_compatible(candidate.role, job.role_family) else 0.0

    candidate_skills = {skill.casefold() for skill in candidate.skills}

    job_skills = {skill.casefold() for skill in job.skills}

    skills_score = (
        30.0 * (len(job_skills & candidate_skills) / len(job_skills)) if job_skills else 0.0
    )

    experience_score = (
        20.0
        if job.experience_min_years is None
        else (
            20.0
            if candidate.years_experience is not None
            and float(candidate.years_experience) >= job.experience_min_years
            else 0.0
        )
    )

    location_score = _location_score(candidate, job)

    freshness_reference = job.posted_at or job.last_seen_at

    age_days = max(
        0.0,
        (datetime.now(UTC) - freshness_reference).total_seconds() / 86400,
    )

    freshness_score = max(
        0.0,
        10.0 - min(age_days, 10.0),
    )

    return {
        "match_score": (
            role_score + skills_score + experience_score + location_score + freshness_score
        ),
        "role_score": role_score,
        "skills_score": skills_score,
        "experience_score": experience_score,
        "location_score": location_score,
        "freshness_score": freshness_score,
    }


def _location_score(
    candidate: Candidate,
    job: MatchableJob,
) -> float:
    """Score remote preference or textual location compatibility."""

    if job.remote and candidate.remote_preferred:
        return 10.0

    if (
        candidate.location
        and job.location
        and candidate.location.casefold() in job.location.casefold()
    ):
        return 10.0

    return 0.0
