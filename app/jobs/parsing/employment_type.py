"""Deterministic employment type and workplace remote normalization."""

from __future__ import annotations

import re


def normalize_employment_type(text: str | None) -> str | None:
    """Normalize employment type into standard terms.

    Standard values: 'full-time', 'part-time', 'contract', 'temporary', 'internship'.
    """
    if not text:
        return None

    lowered = text.casefold()

    if re.search(r"\b(intern(?:ship)?)\b", lowered):
        return "internship"
    if re.search(r"\b(contract(?:or)?|c2c|corp-to-corp|w2 contract|freelance)\b", lowered):
        return "contract"
    if re.search(r"\b(part[ -]?time)\b", lowered):
        return "part-time"
    if re.search(r"\b(full[ -]?time|permanent|direct hire)\b", lowered):
        return "full-time"
    if re.search(r"\b(temp(?:orary)?)\b", lowered):
        return "temporary"

    return None


def normalize_remote_type(text: str | None, remote_flag: bool | None = None) -> str | None:
    """Normalize remote type to 'remote', 'hybrid', 'on_site', or None."""
    if remote_flag is True:
        return "remote"

    if not text:
        return "on_site" if remote_flag is False else None

    lowered = text.casefold()

    if "hybrid" in lowered:
        return "hybrid"
    remote_keywords = ("remote", "telecommute", "work from home", "wfh")
    if any(k in lowered for k in remote_keywords):
        return "remote"
    onsite_keywords = ("on-site", "onsite", "in-office", "in office")
    if any(k in lowered for k in onsite_keywords):
        return "on_site"

    if remote_flag is False:
        return "on_site"

    return None
