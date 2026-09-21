"""Deterministic normalization for source jobs and role matching."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
class RawSourceJob:
    source: str
    external_job_id: str
    title: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    description: str | None = None
    salary_text: str | None = None
    employment_type: str | None = None
    remote: bool | None = None
    posted_at: datetime | None = None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedJob:
    source: str
    external_job_id: str
    job_title: str
    normalized_title: str
    role_family: str
    company: str | None
    location: str | None
    job_url: str | None
    description: str | None
    salary_text: str | None
    employment_type: str | None
    remote: bool | None
    skills: list[str]
    posted_at: datetime | None
    experience_min_years: int | None
    experience_max_years: int | None
    experience_text: str | None
    content_hash: str


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+/#&.-]", " ", title.casefold())).strip()


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


_EXPERIENCE_PATTERNS = (
    re.compile(r"\b(?P<min>\d{1,2})\s*(?:-|\N{EN DASH}|to)\s*(?P<max>\d{1,2})\s+years?\b", re.I),
    re.compile(r"\b(?:minimum|at least)\s+(?P<min>\d{1,2})\s+years?\b", re.I),
    re.compile(r"\b(?P<min>\d{1,2})\s*\+\s*years?\b", re.I),
    re.compile(r"\b(?P<min>\d{1,2})\s+years?\s+(?:of\s+)?(?:professional\s+)?experience\b", re.I),
)


def extract_experience(text: str | None) -> tuple[int | None, int | None, str | None]:
    if not text:
        return None, None, None
    for pattern in _EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            minimum = int(match.group("min"))
            maximum = match.groupdict().get("max")
            return minimum, int(maximum) if maximum else None, match.group(0)
    return None, None, None


def normalize_job(raw: RawSourceJob) -> NormalizedJob:
    title = normalize_title(raw.title)
    minimum, maximum, experience_text = extract_experience(f"{raw.title}\n{raw.description or ''}")
    skills = sorted({skill.strip().casefold() for skill in raw.skills if skill.strip()})
    url = normalize_url(raw.url)
    digest = hashlib.sha256(
        "|".join(
            (raw.source, raw.external_job_id, title, raw.company or "", raw.description or "")
        ).encode()
    ).hexdigest()
    return NormalizedJob(
        raw.source,
        raw.external_job_id,
        raw.title.strip(),
        title,
        normalize_role(raw.title),
        raw.company.strip() if raw.company else None,
        raw.location.strip() if raw.location else None,
        url,
        raw.description,
        raw.salary_text,
        raw.employment_type,
        raw.remote,
        skills,
        raw.posted_at,
        minimum,
        maximum,
        experience_text,
        digest,
    )
