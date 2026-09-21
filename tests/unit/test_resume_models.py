"""Resume and candidate-profile persistence model tests."""

from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy import Table

from app.domain.resumes import CandidateProfile, Resume, ResumeStatus, ResumeStorageCleanup


def test_resume_model_uses_private_schema_and_ownership() -> None:
    table = cast(Table, Resume.__table__)
    assert table.schema == "hireandtech"
    assert table.c.owner_profile_id.nullable is False
    assert table.c.storage_object_key.unique
    assert table.c.content_type.nullable is False
    assert table.c.size_bytes.nullable is False
    assert table.c.sha256.nullable is False

    foreign_keys = {
        foreign_key.target_fullname for foreign_key in table.c.owner_profile_id.foreign_keys
    }

    assert foreign_keys == {"hireandtech.profiles.id"}


def test_resume_status_contains_expected_lifecycle() -> None:
    assert {status.value for status in ResumeStatus} == {
        "uploaded",
        "parsing",
        "parsed",
        "parse_failed",
        "deleted",
    }


def test_resume_declares_security_and_integrity_constraints() -> None:
    table = cast(Table, Resume.__table__)

    constraint_names = {
        constraint.name for constraint in table.constraints if constraint.name is not None
    }

    assert "uq_resumes_id_owner_profile_id" in constraint_names
    assert "ck_resumes_resume_size_positive" in constraint_names
    assert "ck_resumes_resume_sha256_length" in constraint_names
    assert "ck_resumes_resume_pdf_content_type" in constraint_names
    assert "ck_resumes_resume_deleted_state_consistent" in constraint_names
    assert "ck_resumes_resume_sha256_lower_hex" in constraint_names
    assert "ck_resumes_resume_filename_not_blank" in constraint_names
    assert "ck_resumes_resume_parse_error_state_consistent" in constraint_names
    assert "ck_resumes_resume_version_positive" in constraint_names
    assert Resume.__mapper__.version_id_col is table.c.version


def test_storage_cleanup_is_private_durable_and_owner_bound() -> None:
    table = cast(Table, ResumeStorageCleanup.__table__)

    assert table.schema == "hireandtech"
    assert table.c.storage_object_key.unique
    assert table.c.available_at.nullable is False
    assert table.c.attempts.nullable is False
    owner_foreign_key = next(iter(table.c.owner_profile_id.foreign_keys))
    assert owner_foreign_key.target_fullname == "hireandtech.profiles.id"
    assert owner_foreign_key.ondelete == "RESTRICT"


def test_candidate_profile_is_one_to_one_with_resume() -> None:
    table = cast(Table, CandidateProfile.__table__)

    assert table.schema == "hireandtech"
    assert table.c.resume_id.unique
    assert table.c.owner_profile_id.nullable is False

    foreign_key_targets = {
        element.target_fullname
        for constraint in table.foreign_key_constraints
        for element in constraint.elements
    }

    assert "hireandtech.resumes.id" in foreign_key_targets
    assert "hireandtech.resumes.owner_profile_id" in foreign_key_targets
    assert "hireandtech.profiles.id" in foreign_key_targets


def test_candidate_profile_accepts_structured_parser_data() -> None:
    owner_id = uuid4()
    resume_id = uuid4()

    profile = CandidateProfile(
        resume_id=resume_id,
        owner_profile_id=owner_id,
        full_name="Example Candidate",
        email="candidate@example.com",
        years_of_experience=Decimal("5.5"),
        skills=["Python", "FastAPI", "PostgreSQL"],
        employment_history=[
            {
                "company": "Example Company",
                "title": "Backend Engineer",
            }
        ],
        education=[
            {
                "institution": "Example University",
                "qualification": "Bachelor's Degree",
            }
        ],
        certifications=["Example Certification"],
        languages=["English"],
        raw_parser_output={"parser": "test"},
    )

    assert profile.resume_id == resume_id
    assert profile.owner_profile_id == owner_id
    assert profile.years_of_experience == Decimal("5.5")
    assert profile.skills == ["Python", "FastAPI", "PostgreSQL"]
