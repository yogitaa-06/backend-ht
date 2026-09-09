"""Schemas for deterministic resume parsing and safe resume API responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.domain.resumes import ResumeStatus

MAX_EXTRACTED_TEXT_CHARACTERS = 200_000


NormalizedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ResumeSchema(BaseModel):
    """Strict base schema for resume-related structures."""

    model_config = ConfigDict(extra="forbid")


class EmploymentEntry(ResumeSchema):
    """Normalized employment entry extracted from a resume."""

    company: NormalizedText | None = None
    title: NormalizedText | None = None
    location: NormalizedText | None = None
    start_date: NormalizedText | None = None
    end_date: NormalizedText | None = None
    description: NormalizedText | None = None


class EducationEntry(ResumeSchema):
    """Normalized education entry extracted from a resume."""

    institution: NormalizedText | None = None
    qualification: NormalizedText | None = None
    field_of_study: NormalizedText | None = None
    start_date: NormalizedText | None = None
    end_date: NormalizedText | None = None


def _normalize_string_list(values: list[str]) -> list[str]:
    """Trim, discard blanks, and deduplicate strings case-insensitively."""
    normalized: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue

        key = cleaned.casefold()
        if key in seen:
            continue

        seen.add(key)
        normalized.append(cleaned)

    return normalized


class ParsedResume(ResumeSchema):
    """Deterministic parser output before persistence."""

    full_name: NormalizedText | None = None
    email: NormalizedText | None = None
    phone: NormalizedText | None = None
    location: NormalizedText | None = None
    current_title: NormalizedText | None = None
    professional_summary: NormalizedText | None = None
    years_of_experience: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("80"),
    )
    extracted_text: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_EXTRACTED_TEXT_CHARACTERS,
        ),
    ]
    skills: list[str] = Field(default_factory=list)
    employment_history: list[EmploymentEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    raw_parser_output: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "skills",
        "certifications",
        "languages",
        mode="after",
    )
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)


class ResumeResponse(ResumeSchema):
    """Safe public representation of resume metadata."""

    id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    status: ResumeStatus
    parser_version: str | None = None
    parse_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ResumePage(ResumeSchema):
    """Paginated collection of safe resume metadata."""

    items: list[ResumeResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class CandidateProfileResponse(ResumeSchema):
    """Safe public structured candidate profile."""

    id: UUID
    resume_id: UUID
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    current_title: str | None = None
    professional_summary: str | None = None
    years_of_experience: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("80"),
    )
    skills: list[str] = Field(default_factory=list)
    employment_history: list[EmploymentEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ResumeReplaceResponse(ResumeSchema):
    """Safe response returned after replacing a resume."""

    resume: ResumeResponse
    replaced: Literal[True] = True


class ResumeDeleteResponse(ResumeSchema):
    """Safe response returned after deleting a resume."""

    resume_id: UUID
    deleted: Literal[True]
