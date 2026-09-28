"""Deterministic experience extraction from job titles and descriptions."""

from __future__ import annotations

import re
from collections.abc import Callable

# Ordered patterns for extracting experience requirements
_EXPERIENCE_PATTERNS: list[
    tuple[
        re.Pattern[str],
        Callable[[re.Match[str]], tuple[int | None, int | None, str]],
    ]
] = [
    # "3-5 years", "3 - 5 years", "3 to 5 years", "3-5 yrs"
    (
        re.compile(
            r"\b(?P<min>\d{1,2})\s*(?:-|\u2013|\u2014|to)\s*(?P<max>\d{1,2})\s*(?:\+)?\s*(?:years?|yrs?)\b",
            re.IGNORECASE,
        ),
        lambda m: (int(m.group("min")), int(m.group("max")), m.group(0).strip()),
    ),
    # "5+ years", "5 + years", "5+ yrs"
    (
        re.compile(
            r"\b(?P<min>\d{1,2})\s*\+\s*(?:years?|yrs?)\b",
            re.IGNORECASE,
        ),
        lambda m: (int(m.group("min")), None, m.group(0).strip()),
    ),
    # "at least 3 years", "minimum 3 years", "minimum of 3 years"
    (
        re.compile(
            r"\b(?:at least|minimum(?: of)?)\s+(?P<min>\d{1,2})\s*(?:years?|yrs?)\b",
            re.IGNORECASE,
        ),
        lambda m: (int(m.group("min")), None, m.group(0).strip()),
    ),
    # "3 years of experience", "3+ years of experience"
    (
        re.compile(
            r"\b(?P<min>\d{1,2})(?:\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?"
            r"(?:relevant\s+|professional\s+|hands-on\s+)?experience\b",
            re.IGNORECASE,
        ),
        lambda m: (int(m.group("min")), None, m.group(0).strip()),
    ),
]


def extract_experience(text: str | None) -> tuple[int | None, int | None, str | None]:
    """Extract minimum and maximum years of experience and raw text snippet.

    Returns:
        (experience_min, experience_max, experience_text)
        All None if not found or text is empty.
    """
    if not text:
        return None, None, None

    for pattern, extractor in _EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            min_years, max_years, raw_text = extractor(match)
            # Sanity check: filter out unrealistic numbers (e.g. 1999 years or 0 years)
            if min_years is not None and (min_years < 0 or min_years > 30):
                continue
            if max_years is not None and (max_years < 0 or max_years > 30):
                continue
            if min_years is not None and max_years is not None and min_years > max_years:
                min_years, max_years = max_years, min_years
            return min_years, max_years, raw_text

    return None, None, None
