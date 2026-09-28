"""Shared deterministic extraction and normalization utilities for job collectors."""

from app.jobs.parsing.employment_type import (
    normalize_employment_type,
    normalize_remote_type,
)
from app.jobs.parsing.experience import extract_experience
from app.jobs.parsing.salary import parse_salary
from app.jobs.parsing.skills import (
    extract_skills_from_list,
    extract_skills_from_text,
    merge_skills,
    normalize_skill,
)

__all__ = [
    "extract_experience",
    "extract_skills_from_list",
    "extract_skills_from_text",
    "merge_skills",
    "normalize_employment_type",
    "normalize_remote_type",
    "normalize_skill",
    "parse_salary",
]
