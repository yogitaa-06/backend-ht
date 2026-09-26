"""Dice global-job collector.

This module contains Dice-specific HTTP and parsing behavior only.

Persistence, normalization, matching, scheduling, and distributed locking
remain owned by the existing platform services.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from app.core.config import Settings, get_settings
from app.domain.jobs import JobSource
from app.jobs.errors import (
    SourceBlockedError,
    SourceRateLimitedError,
    TemporaryCollectionError,
)
from app.jobs.normalization import DiscoveredSourceJob, RawSourceJob
from app.jobs.targets import CollectionTarget
from app.jobs.transport import build_collection_client

logger = logging.getLogger(__name__)

_DICE_SEARCH_URL = "https://www.dice.com/jobs"
_DICE_JOB_DETAIL_URL = "https://www.dice.com/job-detail"

_DEFAULT_TIMEOUT_SECONDS = 20.0
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGES = 5
_REQUEST_DELAY_SECONDS = 1.0

_JOB_ID_PATTERN = re.compile(
    r"/job-detail/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_GUID_RE = re.compile(
    r"/job-detail/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_FLIGHT_PUSH_RE = re.compile(
    r"self\.__next_f\.push\((\[.*?\])\)\s*;?\s*</script>",
    re.DOTALL,
)


def _iter_flight_chunks(html_content: str) -> list[str]:
    """Extract pushed JSON payload strings from Next.js RSC flight push scripts.

    Modern Dice uses Next.js React Server Components (RSC). Search listings are
    streamed in <script>self.__next_f.push([...])</script> tags as chunked arrays.
    """
    chunks: list[str] = []
    for match in _FLIGHT_PUSH_RE.finditer(html_content):
        try:
            pushed = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(pushed, list) and len(pushed) >= 2 and isinstance(pushed[1], str):
            chunks.append(pushed[1])
    return chunks


def _parse_flight_joblist(html_content: str) -> dict[str, Any] | None:
    """Find and decode the embedded 'jobList' JSON object inside RSC flight chunks."""
    for chunk in _iter_flight_chunks(html_content):
        index = chunk.find('"jobList":')
        if index == -1:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(chunk, index + len('"jobList":'))
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("data"), list):
            return obj
    return None


class DiceCollector:
    """Collect recent public Dice jobs for a platform-owned target."""

    source = JobSource.DICE

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        request_delay_seconds: float = _REQUEST_DELAY_SECONDS,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._request_delay_seconds = request_delay_seconds

    async def collect(
        self,
        target: CollectionTarget,
    ) -> Sequence[RawSourceJob]:
        """Compatibility wrapper that fetches details for every candidate."""
        candidates = await self.discover(target)
        return await self.fetch_details(target, candidates)

    async def discover(
        self,
        target: CollectionTarget,
    ) -> Sequence[DiscoveredSourceJob]:
        """Discover at most target.max_jobs unique lightweight candidates."""

        if target.source is not self.source:
            raise ValueError(f"DiceCollector cannot collect source {target.source.value!r}")

        logger.info(
            "dice_collection_started",
            extra={
                "source": self.source.value,
                "query": target.query,
                "location": target.location,
                "max_jobs": target.max_jobs,
            },
        )

        owns_client = self._client is None
        client = self._client or self._build_client()

        collected: list[DiscoveredSourceJob] = []
        seen_ids: set[str] = set()

        try:
            for page in range(1, _MAX_PAGES + 1):
                if len(collected) >= target.max_jobs:
                    break

                response = await self._fetch_search_page(
                    client,
                    target=target,
                    page=page,
                )

                page_jobs = self._parse_search_response(response.text)

                logger.info(
                    "dice_search_page_completed",
                    extra={
                        "source": self.source.value,
                        "query": target.query,
                        "location": target.location,
                        "page": page,
                        "jobs_on_page": len(page_jobs),
                    },
                )

                if not page_jobs:
                    break

                new_on_page = 0

                for discovered_job in page_jobs:
                    external_job_id = discovered_job.external_job_id

                    if external_job_id in seen_ids:
                        continue

                    seen_ids.add(external_job_id)

                    collected.append(discovered_job)
                    new_on_page += 1

                    if len(collected) >= target.max_jobs:
                        break

                if new_on_page == 0:
                    break

                if len(page_jobs) < _DEFAULT_PAGE_SIZE:
                    break

                if (
                    page < _MAX_PAGES
                    and len(collected) < target.max_jobs
                    and self._request_delay_seconds > 0
                ):
                    await asyncio.sleep(self._request_delay_seconds)

        finally:
            if owns_client:
                await client.aclose()

        logger.info(
            "dice_collection_completed",
            extra={
                "source": self.source.value,
                "query": target.query,
                "location": target.location,
                "jobs_discovered": len(collected),
            },
        )

        return tuple(collected)

    async def fetch_details(
        self,
        target: CollectionTarget,
        candidates: Sequence[DiscoveredSourceJob],
    ) -> Sequence[RawSourceJob]:
        """Fetch and parse details for the coordinator-selected candidates."""
        if target.source is not self.source:
            raise ValueError(f"DiceCollector cannot collect source {target.source.value!r}")
        owns_client = self._client is None
        client = self._client or self._build_client()
        collected: list[RawSourceJob] = []
        try:
            for candidate in candidates:
                if self._request_delay_seconds > 0:
                    await asyncio.sleep(self._request_delay_seconds)
                try:
                    response = await self._fetch_job_detail(
                        client, external_job_id=candidate.external_job_id
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {404, 410}:
                        raise
                    # Search indexes can briefly retain expired listings. Keep
                    # other successful details instead of failing the whole batch.
                    logger.info(
                        "dice_job_detail_unavailable",
                        extra={
                            "source": self.source.value,
                            "external_job_id": candidate.external_job_id,
                            "status_code": exc.response.status_code,
                        },
                    )
                    continue
                detailed_job = self._parse_job_detail(
                    response.text,
                    expected_external_job_id=candidate.external_job_id,
                )
                if detailed_job is None:
                    logger.warning(
                        "dice_job_detail_parse_failed",
                        extra={
                            "source": self.source.value,
                            "external_job_id": candidate.external_job_id,
                        },
                    )
                    continue
                collected.append(detailed_job)
        finally:
            if owns_client:
                await client.aclose()
        return tuple(collected)

    def _build_client(self) -> httpx.AsyncClient:
        """Create the HTTP client used for Dice requests."""
        return build_collection_client(self._settings, timeout_seconds=_DEFAULT_TIMEOUT_SECONDS)

    async def _fetch_search_page(
        self,
        client: httpx.AsyncClient,
        *,
        target: CollectionTarget,
        page: int,
    ) -> httpx.Response:
        """Fetch one Dice search-results page."""

        params: dict[str, str | int] = {
            "q": target.query,
            "page": page,
            "pageSize": _DEFAULT_PAGE_SIZE,
            "filters.postedDate": "SEVEN",
        }

        if target.location and target.location.lower() != "remote":
            params["location"] = target.location
        elif target.location and target.location.lower() == "remote":
            params["filters.workplaceTypes"] = "Remote"

        url = f"{_DICE_SEARCH_URL}?{urlencode(params)}"

        try:
            response = await client.get(url)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TemporaryCollectionError(
                f"Dice request failed for query {target.query!r}"
            ) from exc

        self._raise_for_dice_status(
            response,
            request_description="collection request",
        )

        return response

    async def _fetch_job_detail(
        self,
        client: httpx.AsyncClient,
        *,
        external_job_id: str,
    ) -> httpx.Response:
        """Fetch one Dice job-detail page."""

        url = f"{_DICE_JOB_DETAIL_URL}/{external_job_id}"

        try:
            response = await client.get(url)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TemporaryCollectionError(
                f"Dice detail request failed for job {external_job_id!r}"
            ) from exc

        self._raise_for_dice_status(
            response,
            request_description="job-detail request",
        )

        return response

    @staticmethod
    def _raise_for_dice_status(
        response: httpx.Response,
        *,
        request_description: str,
    ) -> None:
        """Translate Dice HTTP failures into collection errors."""

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")

            try:
                retry_after_seconds = int(retry_after) if retry_after else 60
            except ValueError:
                retry_after_seconds = 60

            raise SourceRateLimitedError(
                f"Dice rate limited the {request_description}",
                retry_after_seconds=retry_after_seconds,
            )

        if response.status_code == 403:
            raise SourceBlockedError(
                f"Dice blocked the {request_description}",
                retry_after_seconds=300,
            )

        if response.status_code in {
            408,
            425,
            502,
            503,
            504,
        }:
            raise TemporaryCollectionError(
                "Dice temporarily failed the "
                f"{request_description} with HTTP "
                f"{response.status_code}"
            )

        response.raise_for_status()

    def _parse_flight_chunks(self, body: str) -> list[DiscoveredSourceJob]:
        """Extract job listings from Next.js RSC flight push chunks."""
        job_list = _parse_flight_joblist(body)
        if not job_list or not isinstance(job_list.get("data"), list):
            return []

        results: list[DiscoveredSourceJob] = []
        for item in job_list["data"]:
            if not isinstance(item, dict):
                continue
            guid = str(item.get("guid") or item.get("id") or "").strip()
            if not guid:
                continue
            title = str(item.get("title") or "Dice Tech Job").strip()
            detail_url = str(item.get("detailsPageUrl") or f"{_DICE_JOB_DETAIL_URL}/{guid}").strip()
            results.append(
                DiscoveredSourceJob(
                    source=self.source.value,
                    external_job_id=guid,
                    title=title,
                    url=detail_url,
                )
            )
        return self._deduplicate(results)

    def _parse_guid_fallback(self, body: str) -> list[DiscoveredSourceJob]:
        """Extract job GUIDs directly using regex when structured data is missing."""
        seen: set[str] = set()
        results: list[DiscoveredSourceJob] = []
        for guid in _GUID_RE.findall(body):
            clean_guid = guid.strip()
            if clean_guid and clean_guid not in seen:
                seen.add(clean_guid)
                results.append(
                    DiscoveredSourceJob(
                        source=self.source.value,
                        external_job_id=clean_guid,
                        title="Dice Tech Job",
                        url=f"{_DICE_JOB_DETAIL_URL}/{clean_guid}",
                    )
                )
        return results

    def _parse_search_response(
        self,
        body: str,
    ) -> list[DiscoveredSourceJob]:
        """Parse Dice search HTML/embedded JSON into discovered jobs."""

        # 1. Next.js RSC Flight streaming parser
        flight_jobs = self._parse_flight_chunks(body)
        if flight_jobs:
            return flight_jobs

        # 2. JSON-LD and application/json scripts
        jobs = self._parse_json_scripts(body)
        if jobs:
            return jobs

        # 3. Fallback: regex GUID extraction
        guid_jobs = self._parse_guid_fallback(body)
        if guid_jobs:
            return guid_jobs

        # 4. Fallback: generic anchor links
        return self._parse_job_links(body)

    def _parse_job_detail(
        self,
        body: str,
        *,
        expected_external_job_id: str,
    ) -> RawSourceJob | None:
        """Parse one Dice JobPosting JSON-LD detail page."""

        script_pattern = re.compile(
            r'<script[^>]+type=["\']'
            r"application/ld\+json"
            r'["\'][^>]*>'
            r"(.*?)</script>",
            re.IGNORECASE | re.DOTALL,
        )

        for match in script_pattern.finditer(body):
            raw_json = match.group(1).strip()

            if not raw_json:
                continue

            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            for candidate in self._walk_json(payload):
                candidate_type = candidate.get("@type")

                if not self._is_job_posting_type(candidate_type):
                    continue

                job = self._job_from_mapping(candidate)

                if job is None:
                    continue

                if job.external_job_id != expected_external_job_id:
                    # Align with expected GUID from URL if JSON-LD identifier is internal
                    job = RawSourceJob(
                        source=job.source,
                        external_job_id=expected_external_job_id,
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        url=job.url or f"{_DICE_JOB_DETAIL_URL}/{expected_external_job_id}",
                        description=job.description,
                        salary_text=job.salary_text,
                        employment_type=job.employment_type,
                        remote=job.remote,
                        posted_at=job.posted_at,
                        source_updated_at=job.source_updated_at,
                        skills=job.skills,
                        raw_data=job.raw_data,
                    )

                return job

        return None

    @staticmethod
    def _is_job_posting_type(value: Any) -> bool:
        """Return whether a JSON-LD @type represents JobPosting."""

        if isinstance(value, str):
            return value == "JobPosting"

        if isinstance(value, list):
            return "JobPosting" in value

        return False

    def _parse_json_scripts(
        self,
        body: str,
    ) -> list[DiscoveredSourceJob]:
        """Parse structured JSON embedded in a Dice page."""

        results: list[DiscoveredSourceJob] = []

        script_pattern = re.compile(
            r'<script[^>]+type=["\']'
            r"application/(?:ld\+json|json)"
            r'["\'][^>]*>'
            r"(.*?)</script>",
            re.IGNORECASE | re.DOTALL,
        )

        for match in script_pattern.finditer(body):
            raw_json = match.group(1).strip()

            if not raw_json:
                continue

            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            for candidate in self._walk_json(payload):
                job = self._job_from_mapping(candidate)

                if job is not None:
                    results.append(
                        DiscoveredSourceJob(
                            source=job.source,
                            external_job_id=job.external_job_id,
                            title=job.title,
                            url=job.url,
                        )
                    )

        return self._deduplicate(results)

    def _walk_json(
        self,
        value: Any,
    ) -> list[Mapping[str, Any]]:
        """Recursively return mapping objects from JSON."""

        mappings: list[Mapping[str, Any]] = []

        if isinstance(value, Mapping):
            mappings.append(value)

            for child in value.values():
                mappings.extend(self._walk_json(child))

        elif isinstance(value, list):
            for child in value:
                mappings.extend(self._walk_json(child))

        return mappings

    def _job_from_mapping(
        self,
        value: Mapping[str, Any],
    ) -> RawSourceJob | None:
        """Convert one Dice JSON mapping into RawSourceJob."""

        title = self._first_text(
            value,
            "title",
            "jobTitle",
            "name",
        )

        url = self._first_text(
            value,
            "url",
            "jobUrl",
            "jobDetailUrl",
            "detailsPageUrl",
        )

        external_id = self._first_text(
            value,
            "guid",
            "id",
            "jobId",
            "jobID",
            "externalId",
            "external_job_id",
        )

        if not external_id:
            identifier = value.get("identifier")

            if isinstance(identifier, Mapping):
                identifier_value = identifier.get("value")

                if isinstance(identifier_value, str) and identifier_value.strip():
                    external_id = identifier_value.strip()

        if not external_id and url:
            external_id = self._extract_job_id(url)

        if not title or not external_id:
            return None

        company = self._extract_company(value)
        location = self._extract_location(value)

        description = self._first_text(
            value,
            "description",
            "jobDescription",
        )

        salary = self._extract_salary(value)

        employment_type = self._extract_employment_type(value)

        posted_at = self._parse_datetime(
            self._first_text(
                value,
                "datePosted",
                "postedDate",
                "posted_at",
                "date",
            )
        )

        source_updated_at = self._parse_datetime(
            self._first_text(value, "dateModified", "modifiedDate", "updated_at")
        )

        skills = self._extract_skills(value)

        remote = self._extract_remote(
            value,
            location,
        )

        return RawSourceJob(
            source=self.source.value,
            external_job_id=external_id,
            title=title,
            company=company,
            location=location,
            url=self._absolute_url(url),
            description=description,
            salary_text=salary,
            employment_type=employment_type,
            remote=remote,
            posted_at=posted_at,
            source_updated_at=source_updated_at,
            skills=skills,
            raw_data=dict(value),
        )

    def _parse_job_links(
        self,
        body: str,
    ) -> list[DiscoveredSourceJob]:
        """Fallback to proven job links when JSON is unavailable."""

        jobs: list[DiscoveredSourceJob] = []

        link_pattern = re.compile(
            r'<a[^>]+href=["\']'
            r'(?P<url>[^"\']*/job-detail/[^"\']+)'
            r'["\'][^>]*>'
            r"(?P<title>.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )

        tag_pattern = re.compile(r"<[^>]+>")

        for match in link_pattern.finditer(body):
            url = match.group("url")
            external_id = self._extract_job_id(url)

            if not external_id:
                continue

            title = tag_pattern.sub(
                " ",
                match.group("title"),
            )
            title = " ".join(title.split())

            if not title:
                continue

            jobs.append(
                DiscoveredSourceJob(
                    source=self.source.value,
                    external_job_id=external_id,
                    title=title,
                    url=self._absolute_url(url),
                )
            )

        return self._deduplicate(jobs)

    @staticmethod
    def _first_text(
        value: Mapping[str, Any],
        *keys: str,
    ) -> str | None:
        """Return the first non-empty scalar text value."""

        for key in keys:
            candidate = value.get(key)

            if isinstance(candidate, str):
                candidate = " ".join(candidate.split())

                if candidate:
                    return candidate

            if isinstance(candidate, (int, float)):
                return str(candidate)

        return None

    def _extract_company(
        self,
        value: Mapping[str, Any],
    ) -> str | None:
        """Extract the employer name."""

        company = value.get("hiringOrganization")

        if isinstance(company, Mapping):
            name = company.get("name")

            if isinstance(name, str) and name.strip():
                return " ".join(name.split())

        company = value.get("company")

        if isinstance(company, Mapping):
            name = company.get("name")

            if isinstance(name, str) and name.strip():
                return " ".join(name.split())

        return self._first_text(
            value,
            "companyName",
            "company",
            "employerName",
        )

    def _extract_location(
        self,
        value: Mapping[str, Any],
    ) -> str | None:
        """Extract a normalized human-readable Dice location."""

        direct = self._first_text(
            value,
            "location",
            "formattedLocation",
        )

        if direct:
            return direct

        location = value.get("jobLocation")

        if isinstance(location, list):
            locations = [
                self._location_from_mapping(item) for item in location if isinstance(item, Mapping)
            ]

            valid_locations = [item for item in locations if item]

            return " | ".join(valid_locations) if valid_locations else None

        if isinstance(location, Mapping):
            return self._location_from_mapping(location)

        return None

    @staticmethod
    def _location_from_mapping(
        location: Mapping[str, Any],
    ) -> str | None:
        """Extract city/state/country from JobPosting location."""

        address = location.get("address")

        if not isinstance(address, Mapping):
            return None

        parts: list[str] = []

        for key in (
            "addressLocality",
            "addressRegion",
            "addressCountry",
        ):
            part = address.get(key)

            if isinstance(part, str) and part.strip():
                parts.append(part.strip())

        return ", ".join(parts) or None

    def _extract_salary(
        self,
        value: Mapping[str, Any],
    ) -> str | None:
        """Extract Dice salary text or structured base salary."""

        direct = self._first_text(
            value,
            "salary",
            "salaryText",
        )

        if direct:
            return direct

        base_salary = value.get("baseSalary")

        if not isinstance(base_salary, Mapping):
            return None

        currency = base_salary.get("currency")
        salary_value = base_salary.get("value")

        source: Mapping[str, Any]

        if isinstance(salary_value, Mapping):
            source = salary_value
        else:
            source = base_salary

        min_value = source.get("minValue")
        max_value = source.get("maxValue")
        exact_value = source.get("value")
        unit_text = source.get("unitText")

        amount: str | None = None

        if isinstance(
            min_value,
            (int, float),
        ) and isinstance(
            max_value,
            (int, float),
        ):
            amount = f"{self._format_number(min_value)} - {self._format_number(max_value)}"

        elif isinstance(
            min_value,
            (int, float),
        ):
            amount = f"{self._format_number(min_value)}+"

        elif isinstance(
            max_value,
            (int, float),
        ):
            amount = f"Up to {self._format_number(max_value)}"

        elif isinstance(
            exact_value,
            (int, float),
        ):
            amount = self._format_number(exact_value)

        if amount is None:
            return None

        parts: list[str] = []

        if isinstance(currency, str) and currency.strip():
            parts.append(currency.strip())

        parts.append(amount)

        if isinstance(unit_text, str) and unit_text.strip():
            parts.append(f"per {unit_text.strip().lower()}")

        return " ".join(parts)

    @staticmethod
    def _format_number(
        value: int | float,
    ) -> str:
        """Format structured salary numbers without needless .0."""

        if isinstance(value, float) and value.is_integer():
            return str(int(value))

        return str(value)

    def _extract_employment_type(
        self,
        value: Mapping[str, Any],
    ) -> str | None:
        """Extract Dice employment type."""

        employment_type = value.get("employmentType")

        if isinstance(employment_type, str):
            return " ".join(employment_type.split()) or None

        if isinstance(employment_type, list):
            values = [str(item).strip() for item in employment_type if str(item).strip()]

            return ", ".join(values) or None

        return None

    def _extract_skills(
        self,
        value: Mapping[str, Any],
    ) -> tuple[str, ...]:
        """Extract only explicitly structured Dice skills."""

        raw = value.get("skills")

        if isinstance(raw, str):
            values = re.split(
                r"[,|;]",
                raw,
            )

            return tuple(skill.strip() for skill in values if skill.strip())

        if isinstance(raw, list):
            return tuple(str(skill).strip() for skill in raw if str(skill).strip())

        return ()

    @staticmethod
    def _extract_remote(
        value: Mapping[str, Any],
        location: str | None,
    ) -> bool | None:
        """Extract remote status without inventing missing values."""

        for key in (
            "remote",
            "isRemote",
        ):
            candidate = value.get(key)

            if isinstance(candidate, bool):
                return candidate

        workplace = value.get("jobLocationType")

        if isinstance(workplace, str):
            lowered = workplace.casefold()

            if "telecommute" in lowered or "remote" in lowered:
                return True

        if location and "remote" in location.casefold():
            return True

        return None

    @staticmethod
    def _parse_datetime(
        value: str | None,
    ) -> datetime | None:
        """Parse Dice timestamps into timezone-aware UTC datetimes."""

        if not value:
            return None

        candidate = value.strip()

        try:
            parsed = datetime.fromisoformat(
                candidate.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)

        return parsed.astimezone(UTC)

    @staticmethod
    def _extract_job_id(
        url: str,
    ) -> str | None:
        """Extract Dice's stable job ID from a detail URL."""

        match = _JOB_ID_PATTERN.search(url)

        if match is None:
            return None

        return match.group(1)

    @staticmethod
    def _absolute_url(
        url: str | None,
    ) -> str | None:
        """Convert a Dice-relative URL into an absolute URL."""

        if not url:
            return None

        return urljoin(
            "https://www.dice.com",
            url,
        )

    @staticmethod
    def _deduplicate(
        jobs: Sequence[DiscoveredSourceJob],
    ) -> list[DiscoveredSourceJob]:
        """Deduplicate jobs by Dice external ID."""

        unique: list[DiscoveredSourceJob] = []
        seen: set[str] = set()

        for job in jobs:
            if job.external_job_id in seen:
                continue

            seen.add(job.external_job_id)
            unique.append(job)

        return unique
