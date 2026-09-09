"""Resume parser-contract and safe response-schema tests."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.resumes import ResumeStatus
from app.schemas.resumes import (
    CandidateProfileResponse,
    EducationEntry,
    EmploymentEntry,
    ParsedResume,
    ResumeDeleteResponse,
    ResumeResponse,
)


def test_parsed_resume_normalizes_text_and_string_lists() -> None:
    parsed = ParsedResume(
        full_name="  Example Candidate  ",
        email="  candidate@example.com ",
        extracted_text="Resume content",
        skills=[" Python ", "python", "", "FastAPI"],
        certifications=[" AWS ", "aws"],
        languages=[" English ", "english"],
    )

    assert parsed.full_name == "Example Candidate"
    assert parsed.email == "candidate@example.com"
    assert parsed.skills == ["Python", "FastAPI"]
    assert parsed.certifications == ["AWS"]
    assert parsed.languages == ["English"]


def test_parsed_resume_rejects_empty_or_excessive_text() -> None:
    with pytest.raises(ValidationError):
        ParsedResume(extracted_text="")

    with pytest.raises(ValidationError):
        ParsedResume(extracted_text="x" * 200_001)


def test_parsed_resume_validates_experience_range() -> None:
    valid = ParsedResume(
        extracted_text="Resume content",
        years_of_experience=Decimal("7.5"),
    )

    assert valid.years_of_experience == Decimal("7.5")

    with pytest.raises(ValidationError):
        ParsedResume(
            extracted_text="Resume content",
            years_of_experience=Decimal("-1"),
        )

    with pytest.raises(ValidationError):
        ParsedResume(
            extracted_text="Resume content",
            years_of_experience=Decimal("81"),
        )


def test_nested_parser_entries_reject_unknown_fields() -> None:
    employment = EmploymentEntry(
        company="Example Company",
        title="Backend Engineer",
    )
    education = EducationEntry(
        institution="Example University",
        qualification="Bachelor's Degree",
    )

    assert employment.company == "Example Company"
    assert education.institution == "Example University"

    with pytest.raises(ValidationError):
        EmploymentEntry.model_validate(
            {
                "company": "Example Company",
                "title": "Backend Engineer",
                "unexpected": "not allowed",
            }
        )


def test_resume_response_excludes_private_storage_fields() -> None:
    now = datetime.now(UTC)

    response = ResumeResponse(
        id=uuid4(),
        original_filename="resume.pdf",
        content_type="application/pdf",
        size_bytes=1_024,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
        parse_error_code=None,
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump()

    assert "storage_bucket" not in data
    assert "storage_object_key" not in data
    assert "sha256" not in data
    assert "owner_profile_id" not in data
    assert "extracted_text" not in data
    assert "raw_parser_output" not in data


def test_candidate_profile_response_excludes_raw_content() -> None:
    now = datetime.now(UTC)

    response = CandidateProfileResponse(
        id=uuid4(),
        resume_id=uuid4(),
        full_name="Example Candidate",
        email="candidate@example.com",
        phone=None,
        location=None,
        current_title="Backend Engineer",
        professional_summary=None,
        years_of_experience=Decimal("5.0"),
        skills=["Python"],
        employment_history=[],
        education=[],
        certifications=[],
        languages=["English"],
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump()

    assert "owner_profile_id" not in data
    assert "extracted_text" not in data
    assert "raw_parser_output" not in data


def test_delete_response_requires_success() -> None:
    response = ResumeDeleteResponse(
        resume_id=uuid4(),
        deleted=True,
    )

    assert response.deleted

    with pytest.raises(ValidationError):
        ResumeDeleteResponse(
            resume_id=uuid4(),
            deleted=False,
        )
