"""Deterministic normalization for source jobs and role matching."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unicodedata import normalize as unicode_normalize
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.jobs.parsing import (
    extract_experience,
    extract_skills_from_text,
    merge_skills,
    normalize_employment_type,
    normalize_remote_type,
    parse_salary,
)

ROLE_FAMILIES = {
    "backend",
    "frontend",
    "fullstack",
    "software_engineering",
    "devops",
    "sre",
    "platform",
    "cloud",
    "data_engineering",
    "data_science",
    "machine_learning",
    "qa",
    "security",
    "mobile",
    "accounting",
    "marketing",
    "product_management",
    "other",
}
ROLE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "devops": frozenset({"devops", "sre", "platform", "cloud"}),
    "sre": frozenset({"devops", "sre", "platform", "cloud"}),
    "platform": frozenset({"devops", "sre", "platform", "cloud"}),
    "cloud": frozenset({"devops", "sre", "platform", "cloud"}),
    "backend": frozenset({"backend", "software_engineering", "fullstack"}),
    "frontend": frozenset({"frontend", "fullstack"}),
    "fullstack": frozenset({"fullstack", "backend", "frontend", "software_engineering"}),
    "software_engineering": frozenset({"software_engineering", "backend", "frontend", "fullstack"}),
    "data_engineering": frozenset({"data_engineering"}),
    "data_science": frozenset({"data_science", "machine_learning"}),
    "machine_learning": frozenset({"machine_learning", "data_science"}),
    "qa": frozenset({"qa"}),
    "security": frozenset({"security"}),
    "mobile": frozenset({"mobile"}),
}


@dataclass(frozen=True)
class DiscoveredSourceJob:
    """Lightweight source result used before detail fetching."""

    source: str
    external_job_id: str
    title: str
    url: str | None = None



@dataclass(frozen=True)
class RawSourceJob:
    """Source-neutral job payload emitted by every collector adapter."""

    source: str
    external_job_id: str
    title: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    description: str | None = None
    salary_text: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    employment_type: str | None = None
    remote: bool | None = None
    remote_type: str | None = None
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None
    skills: tuple[str, ...] = ()
    experience_min_years: int | None = None
    experience_max_years: int | None = None
    experience_text: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedJob:
    source: str
    external_job_id: str
    job_title: str
    normalized_title: str
    role_family: str
    company: str | None
    normalized_company: str | None
    location: str | None
    normalized_location: str | None
    job_url: str | None
    description: str | None
    salary_text: str | None
    employment_type: str | None
    remote: bool | None
    skills: list[str]
    posted_at: datetime | None
    source_updated_at: datetime | None
    experience_min_years: int | None
    experience_max_years: int | None
    experience_text: str | None
    content_hash: str
    raw_data: dict[str, Any]
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    remote_type: str | None = None


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+/#&.-]", " ", title.casefold())).strip()


def normalize_company_name(company: str) -> str:
    """Normalize exact employer names without fuzzy or suffix-based merging."""
    return " ".join(unicode_normalize("NFKC", company).casefold().split())


def normalize_location(location: str) -> str:
    """Normalize location formatting while preserving meaningful punctuation."""
    return " ".join(unicode_normalize("NFKC", location).casefold().split())


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if not key.casefold().startswith(("utm_", "trk", "ref"))
    ]
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            urlencode(query),
            "",
        )
    )


def normalize_role(title: str) -> str:
    value = normalize_title(title)
    if re.search(r"\b(site reliability|sre)\b", value):
        return "sre"
    if re.search(r"\b(devops|dev ops)\b", value):
        return "devops"
    if re.search(r"\b(platform|infrastructure)\b", value):
        return "platform"
    if re.search(r"\bcloud\b", value):
        return "cloud"
    if re.search(r"\b(full[ -]?stack)\b", value):
        return "fullstack"
    if re.search(r"\b(front[ -]?end|react|angular|vue)\b", value):
        return "frontend"
    if re.search(r"\b(back[ -]?end|api engineer)\b", value):
        return "backend"
    if re.search(r"\b(machine learning|ml engineer)\b", value):
        return "machine_learning"
    if re.search(r"\b(data scientist|data science)\b", value):
        return "data_science"
    if re.search(r"\b(data engineer|analytics engineer)\b", value):
        return "data_engineering"
    if re.search(r"\b(qa|quality assurance|test automation)\b", value):
        return "qa"
    if re.search(r"\b(security|cyber)\b", value):
        return "security"
    if re.search(r"\b(ios|android|mobile)\b", value):
        return "mobile"
    if re.search(r"\b(accountant|accounting)\b", value):
        return "accounting"
    if re.search(r"\b(product manager|product management)\b", value):
        return "product_management"
    if re.search(r"\b(marketing)\b", value):
        return "marketing"
    if re.search(r"\b(software engineer|software developer)\b", value):
        return "software_engineering"
    return "other"


def roles_compatible(candidate_role: str, job_role: str) -> bool:
    return job_role in ROLE_COMPATIBILITY.get(
        normalize_role(candidate_role), frozenset({normalize_role(candidate_role)})
    )


def normalize_job(raw: RawSourceJob) -> NormalizedJob:
    source = raw.source.strip().casefold()
    external_job_id = raw.external_job_id.strip()
    job_title = " ".join(raw.title.split())
    if not source or not external_job_id or not job_title:
        raise ValueError("source, external job ID, and title must not be blank")

    title = normalize_title(job_title)

    # 1. Experience
    minimum = raw.experience_min_years
    maximum = raw.experience_max_years
    experience_text = raw.experience_text
    if minimum is None and maximum is None and not experience_text:
        minimum, maximum, experience_text = extract_experience(
            f"{raw.title}\n{raw.description or ''}"
        )

    # 2. Salary
    salary_min = raw.salary_min
    salary_max = raw.salary_max
    salary_curr = raw.salary_currency
    salary_period = raw.salary_period
    salary_text = raw.salary_text
    if salary_min is None and salary_max is None:
        p_min, p_max, p_curr, p_period, p_text = parse_salary(
            f"{raw.salary_text or ''}\n{raw.description or ''}"
        )
        if p_min is not None or p_max is not None:
            salary_min, salary_max = p_min, p_max
            salary_curr = p_curr
            salary_period = p_period
            if not salary_text:
                salary_text = p_text

    # 3. Skills
    skills = sorted(
        merge_skills(raw.skills, extract_skills_from_text(raw.description)),
        key=str.casefold,
    )

    # 4. Employment type & Remote
    employment_type = raw.employment_type
    if not employment_type:
        employment_type = normalize_employment_type(f"{raw.title}\n{raw.description or ''}")
    remote_type = raw.remote_type or normalize_remote_type(
        f"{raw.location or ''}\n{raw.description or ''}", remote_flag=raw.remote
    )
    remote = raw.remote
    if remote is None and remote_type == "remote":
        remote = True

    url = normalize_url(raw.url)
    company = " ".join(raw.company.split()) if raw.company else None
    location = " ".join(raw.location.split()) if raw.location else None
    posted_at = _as_utc(raw.posted_at)
    source_updated_at = _as_utc(raw.source_updated_at)
    content = {
        "company": company,
        "description": raw.description,
        "employment_type": employment_type,
        "job_url": url,
        "location": location,
        "posted_at": posted_at.isoformat() if posted_at else None,
        "remote": remote,
        "salary_text": salary_text,
        "skills": sorted(s.casefold() for s in skills),
        "source_updated_at": source_updated_at.isoformat() if source_updated_at else None,
        "title": job_title,
    }
    digest = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return NormalizedJob(
        source,
        external_job_id,
        job_title,
        title,
        normalize_role(job_title),
        company,
        normalize_company_name(company) if company else None,
        location,
        normalize_location(location) if location else None,
        url,
        raw.description,
        salary_text,
        employment_type,
        remote,
        skills,
        posted_at,
        source_updated_at,
        minimum,
        maximum,
        experience_text,
        digest,
        raw.raw_data,
        salary_min,
        salary_max,
        salary_curr,
        salary_period,
        remote_type,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
