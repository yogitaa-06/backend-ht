"""Hard eligibility and deterministic ranking for recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.domain.jobs import GlobalJob
from app.jobs.normalization import roles_compatible


@dataclass(frozen=True)
class Candidate:
    role: str
    years_experience: Decimal | float | None
    skills: frozenset[str]
    location: str | None = None
    remote_preferred: bool | None = None


def experience_compatible(candidate_years: Decimal | float | None, minimum: int | None) -> bool:
    return candidate_years is None or minimum is None or float(candidate_years) >= minimum


def is_eligible(candidate: Candidate, job: GlobalJob) -> bool:
    return (
        job.is_active
        and roles_compatible(candidate.role, job.role_family)
        and experience_compatible(candidate.years_experience, job.experience_min_years)
    )


def rank_job(candidate: Candidate, job: GlobalJob) -> dict[str, float]:
    role_score = 30.0 if job.role_family == job.role_family else 0.0
    job_skills = {skill.casefold() for skill in job.skills}
    skills_score = (
        30.0 * (len(job_skills & candidate.skills) / len(job_skills)) if job_skills else 0.0
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
    location_score = (
        10.0
        if job.remote and candidate.remote_preferred
        else (
            10.0
            if candidate.location
            and job.location
            and candidate.location.casefold() in job.location.casefold()
            else 0.0
        )
    )
    age_days = max(
        0.0, (datetime.now(UTC) - (job.posted_at or job.last_seen_at)).total_seconds() / 86400
    )
    freshness_score = max(0.0, 10.0 - min(age_days, 10.0))
    return {
        "match_score": role_score
        + skills_score
        + experience_score
        + location_score
        + freshness_score,
        "role_score": role_score,
        "skills_score": skills_score,
        "experience_score": experience_score,
        "location_score": location_score,
        "freshness_score": freshness_score,
    }
