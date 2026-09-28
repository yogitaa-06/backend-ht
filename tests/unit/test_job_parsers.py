"""Unit tests for shared deterministic job parsers."""

from decimal import Decimal

from app.jobs.parsing import (
    extract_experience,
    extract_skills_from_list,
    extract_skills_from_text,
    merge_skills,
    normalize_employment_type,
    normalize_remote_type,
    parse_salary,
)


def test_skills_normalization_and_deduplication() -> None:
    raw = ["python", "Python", "PYTHON", "react.js", "FastAPI", "K8s", "c++", "unknown_xyz_skill"]
    cleaned = extract_skills_from_list(raw)
    assert "Python" in cleaned
    assert cleaned.count("Python") == 1
    assert "React" in cleaned
    assert "FastAPI" in cleaned
    assert "Kubernetes" in cleaned
    assert "C++" in cleaned


def test_skills_extraction_from_description() -> None:
    desc = (
        "We are looking for a Python Backend Engineer with experience in FastAPI, "
        "PostgreSQL, Docker and AWS. Nice to have: Kubernetes and C#."
    )
    skills = extract_skills_from_text(desc)
    assert set(skills) >= {"Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Kubernetes", "C#"}


def test_merge_skills() -> None:
    explicit = ["python", "react"]
    text = ["FastAPI", "Python", "Docker"]
    merged = merge_skills(explicit, text)
    assert merged == ["Python", "React", "FastAPI", "Docker"]


def test_experience_extraction() -> None:
    # Range
    min_y, max_y, text = extract_experience("Candidate must have 3-5 years of backend experience.")
    assert (min_y, max_y) == (3, 5)
    assert text == "3-5 years"

    # Plus
    min_y, max_y, text = extract_experience(
        "Requires 5+ years of experience in distributed systems."
    )
    assert (min_y, max_y) == (5, None)
    assert text == "5+ years"

    # At least
    min_y, max_y, text = extract_experience(
        "At least 2 years of professional software engineering."
    )
    assert (min_y, max_y) == (2, None)
    assert text == "At least 2 years"

    # None
    min_y, max_y, text = extract_experience("Looking for enthusiasm and passion.")
    assert (min_y, max_y, text) == (None, None, None)


def test_salary_parsing() -> None:
    # Yearly range with k
    min_s, max_s, curr, period, text = parse_salary(
        "Salary range is $120k-$160k/year based on experience."
    )
    assert min_s == Decimal("120000")
    assert max_s == Decimal("160000")
    assert curr == "USD"
    assert period == "year"

    # Hourly range
    min_s, max_s, curr, period, text = parse_salary("Compensation: $70 - $90/hr")
    assert min_s == Decimal("70")
    assert max_s == Decimal("90")
    assert curr == "USD"
    assert period == "hour"

    # Single annual
    min_s, max_s, curr, period, text = parse_salary("Offering $150,000 annually")
    assert min_s == Decimal("150000")
    assert max_s == Decimal("150000")
    assert curr == "USD"
    assert period == "year"

    # Missing salary
    min_s, max_s, curr, period, text = parse_salary("Competitive benefits package.")
    assert (min_s, max_s, curr, period, text) == (None, None, None, None, None)


def test_employment_and_remote_type_normalization() -> None:
    assert normalize_employment_type("Full Time") == "full-time"
    assert normalize_employment_type("Contract - Corp-To-Corp") == "contract"
    assert normalize_employment_type("Part-time position") == "part-time"

    assert normalize_remote_type("Remote / Telecommute") == "remote"
    assert normalize_remote_type("Hybrid - 2 days in office") == "hybrid"
    assert normalize_remote_type("On-site in New York") == "on_site"
    assert normalize_remote_type(None, remote_flag=True) == "remote"
