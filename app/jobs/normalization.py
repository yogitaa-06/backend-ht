"""Compatibility imports for source-job normalization.

The ingestion package owns normalization. This module remains temporarily so
external scripts and downstream imports can migrate without a flag day.
"""

from app.jobs.ingestion.normalization import (
    ROLE_COMPATIBILITY,
    ROLE_FAMILIES,
    DiscoveredSourceJob,
    NormalizedJob,
    RawSourceJob,
    extract_experience,
    normalize_company_name,
    normalize_job,
    normalize_location,
    normalize_role,
    normalize_title,
    normalize_url,
    roles_compatible,
)

__all__ = [
    "ROLE_COMPATIBILITY",
    "ROLE_FAMILIES",
    "DiscoveredSourceJob",
    "NormalizedJob",
    "RawSourceJob",
    "extract_experience",
    "normalize_company_name",
    "normalize_job",
    "normalize_location",
    "normalize_role",
    "normalize_title",
    "normalize_url",
    "roles_compatible",
]
