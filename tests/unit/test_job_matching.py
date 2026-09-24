from datetime import UTC, datetime
from decimal import Decimal

from app.domain.jobs import GlobalJob
from app.jobs.matching import Candidate, experience_compatible, is_eligible
from app.jobs.normalization import (
    RawSourceJob,
    extract_experience,
    normalize_job,
    normalize_role,
    roles_compatible,
)


def test_role_normalization_and_compatibility() -> None:
    assert normalize_role("Cloud DevOps Engineer") == "devops"
    assert normalize_role("Site Reliability Engineer") == "sre"
    assert roles_compatible("DevOps Engineer", "sre")
    assert not roles_compatible("DevOps Engineer", "frontend")


def test_experience_extraction_is_conservative() -> None:
    assert extract_experience("2+ years")[:2] == (2, None)
    assert extract_experience("3-5 years")[:2] == (3, 5)
    assert extract_experience("3 to 5 years")[:2] == (3, 5)
    assert extract_experience("minimum 3 years")[:2] == (3, None)
    assert extract_experience("at least 4 years")[:2] == (4, None)
    assert extract_experience("salary $120,000 in 2025") == (None, None, None)


def test_experience_policy_is_range_compatible() -> None:
    assert experience_compatible(Decimal("2"), 2)
    assert experience_compatible(Decimal("2"), 3) is False
    assert experience_compatible(Decimal("2"), None)


def test_devops_business_case() -> None:
    candidate = Candidate("DevOps Engineer", Decimal("2"), frozenset({"aws"}))
    jobs = []
    for title, minimum in (
        ("DevOps Engineer", 2),
        ("Junior DevOps Engineer", 1),
        ("Site Reliability Engineer", 2),
        ("Senior DevOps Engineer", 5),
        ("Frontend Engineer", 2),
        ("Data Scientist", 2),
        ("DevOps Engineer", None),
    ):
        job = GlobalJob(
            job_title=title,
            role_family=normalize_role(title),
            is_active=True,
            experience_min_years=minimum,
            skills=[],
            last_seen_at=datetime.now(UTC),
        )
        jobs.append(is_eligible(candidate, job))
    assert jobs == [True, True, True, False, False, False, True]


def test_normalization_hash_is_stable() -> None:
    raw = RawSourceJob("dice", "123", " DevOps Engineer ", skills=("AWS", "aws"))
    normalized = normalize_job(raw)
    assert normalized.role_family == "devops"
    assert normalized.skills == ["aws"]
    assert normalized.content_hash == normalize_job(raw).content_hash


def test_normalization_removes_tracking_without_changing_source_identity() -> None:
    raw = RawSourceJob(
        "dice",
        "123",
        "DevOps Engineer",
        url="https://www.DICE.com/job-detail/123/?utm_source=email&ref=feed#top",
    )

    normalized = normalize_job(raw)

    assert normalized.external_job_id == "123"
    assert normalized.job_url == "https://www.dice.com/job-detail/123"


def test_normalization_preserves_available_detail_fields_without_synthesizing_posted_at() -> None:
    posted_at = datetime(2026, 9, 11, 14, 32, 19, tzinfo=UTC)
    normalized = normalize_job(
        RawSourceJob(
            "dice",
            "detail-1",
            "Senior Security Engineer",
            company="Example Corp",
            location="New York, NY, US",
            url="https://www.dice.com/job-detail/detail-1",
            description="Protect services.",
            salary_text="USD 150000 per year",
            employment_type="FULL_TIME",
            remote=False,
            posted_at=posted_at,
            skills=("Python", "AWS"),
        )
    )

    assert normalized.company == "Example Corp"
    assert normalized.location == "New York, NY, US"
    assert normalized.description == "Protect services."
    assert normalized.salary_text == "USD 150000 per year"
    assert normalized.employment_type == "FULL_TIME"
    assert normalized.remote is False
    assert normalized.posted_at == posted_at
    assert normalized.skills == ["aws", "python"]
    assert normalize_job(RawSourceJob("dice", "detail-2", "Engineer")).posted_at is None
