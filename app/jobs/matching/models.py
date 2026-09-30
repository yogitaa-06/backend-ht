"""Framework-independent data structures for deterministic matching."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Candidate:
    """Structured candidate signals used by eligibility and scoring."""

    role: str
    years_experience: Decimal | float | None
    skills: frozenset[str]
    location: str | None = None
    remote_preferred: bool | None = None


class MatchableJob(Protocol):
    """Persistence-neutral view required by the matching domain."""

    @property
    def id(self) -> UUID: ...

    @property
    def role_family(self) -> str: ...

    @property
    def experience_min_years(self) -> int | None: ...

    @property
    def skills(self) -> list[str]: ...

    @property
    def location(self) -> str | None: ...

    @property
    def posted_at(self) -> datetime | None: ...

    @property
    def last_seen_at(self) -> datetime: ...

    @property
    def is_active(self) -> bool: ...

    @property
    def remote(self) -> bool | None: ...


@dataclass(frozen=True, slots=True)
class JobMatchScore:
    """Typed score components persisted or exposed by recommendation flows."""

    overall_score: float
    role_score: float
    skills_score: float
    experience_score: float
    location_score: float
    freshness_score: float

    def as_legacy_mapping(self) -> dict[str, float]:
        """Return the existing public shape while callers migrate to the type."""
        return {
            "match_score": self.overall_score,
            "role_score": self.role_score,
            "skills_score": self.skills_score,
            "experience_score": self.experience_score,
            "location_score": self.location_score,
            "freshness_score": self.freshness_score,
        }
