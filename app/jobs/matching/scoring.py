"""Deterministic component scoring without HTTP or persistence dependencies."""

from datetime import UTC, datetime

from app.jobs.ingestion.normalization import roles_compatible
from app.jobs.matching.models import Candidate, JobMatchScore, MatchableJob


def score_job(
    candidate: Candidate,
    job: MatchableJob,
    *,
    now: datetime | None = None,
) -> JobMatchScore:
    """Calculate a deterministic, explainable score for one eligible job."""
    role_score = 30.0 if roles_compatible(candidate.role, job.role_family) else 0.0
    candidate_skills = {skill.casefold() for skill in candidate.skills}
    job_skills = {skill.casefold() for skill in job.skills}
    skills_score = (
        30.0 * (len(job_skills & candidate_skills) / len(job_skills)) if job_skills else 0.0
    )
    experience_score = (
        20.0
        if job.experience_min_years is None
        or (
            candidate.years_experience is not None
            and float(candidate.years_experience) >= job.experience_min_years
        )
        else 0.0
    )
    location_score = _location_score(candidate, job)
    freshness_reference = job.posted_at or job.last_seen_at
    age_days = max(
        0.0,
        ((now or datetime.now(UTC)) - freshness_reference).total_seconds() / 86400,
    )
    freshness_score = max(0.0, 10.0 - min(age_days, 10.0))
    return JobMatchScore(
        overall_score=(
            role_score + skills_score + experience_score + location_score + freshness_score
        ),
        role_score=role_score,
        skills_score=skills_score,
        experience_score=experience_score,
        location_score=location_score,
        freshness_score=freshness_score,
    )


def _location_score(candidate: Candidate, job: MatchableJob) -> float:
    if job.remote and candidate.remote_preferred:
        return 10.0
    if (
        candidate.location
        and job.location
        and candidate.location.casefold() in job.location.casefold()
    ):
        return 10.0
    return 0.0
