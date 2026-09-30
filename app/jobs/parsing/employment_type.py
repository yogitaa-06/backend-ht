"""Deterministic employment type and workplace remote normalization."""

from __future__ import annotations

import re

from app.jobs.types import EmploymentType, RemoteType


def normalize_employment_type(text: str | None) -> EmploymentType | None:
    """Normalize employment type into standard terms.

    Standard values: 'full-time', 'part-time', 'contract', 'temporary', 'internship'.
    """
    if not text:
        return None

    lowered = text.casefold()

    if re.search(r"\b(intern(?:ship)?)\b", lowered):
        return EmploymentType.INTERNSHIP
    if re.search(r"\b(contract(?:or)?|c2c|corp-to-corp|w2 contract|freelance)\b", lowered):
        return EmploymentType.CONTRACT
    if re.search(r"\b(part[ _-]?time)\b", lowered):
        return EmploymentType.PART_TIME
    if re.search(r"\b(full[ _-]?time|permanent|direct hire)\b", lowered):
        return EmploymentType.FULL_TIME
    if re.search(r"\b(temp(?:orary)?)\b", lowered):
        return EmploymentType.TEMPORARY

    return None


def normalize_remote_type(text: str | None, remote_flag: bool | None = None) -> RemoteType | None:
    """Normalize remote type to 'remote', 'hybrid', 'on_site', or None."""
    if remote_flag is True:
        return RemoteType.REMOTE

    if not text:
        return RemoteType.ON_SITE if remote_flag is False else None

    lowered = text.casefold()

    if "hybrid" in lowered:
        return RemoteType.HYBRID
    remote_keywords = ("remote", "telecommute", "work from home", "wfh")
    if any(k in lowered for k in remote_keywords):
        return RemoteType.REMOTE
    onsite_keywords = ("on-site", "onsite", "in-office", "in office")
    if any(k in lowered for k in onsite_keywords):
        return RemoteType.ON_SITE

    if remote_flag is False:
        return RemoteType.ON_SITE

    return None
