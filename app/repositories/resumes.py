"""Compatibility imports for resume persistence."""

from app.resumes.repository import (
    CandidateProfileRepository,
    ResumeRepository,
    ResumeStorageCleanupRepository,
)

__all__ = [
    "CandidateProfileRepository",
    "ResumeRepository",
    "ResumeStorageCleanupRepository",
]
