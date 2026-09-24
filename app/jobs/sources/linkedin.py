"""LinkedIn global-job collector.

This module contains LinkedIn-specific HTTP and parsing behavior only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.domain.jobs import JobSource
from app.jobs.errors import (
    SourceBlockedError,
    SourceRateLimitedError,
    TemporaryCollectionError,
)
from app.jobs.normalization import DiscoveredSourceJob, RawSourceJob
from app.jobs.targets import CollectionTarget

logger = logging.getLogger(__name__)

_LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LINKEDIN_JOB_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"

_DEFAULT_TIMEOUT_SECONDS = 20.0
_DEFAULT_PAGE_SIZE = 25
_MAX_PAGES = 5
_REQUEST_DELAY_SECONDS = 2.0


class LinkedInCollector:
    """Collect recent public LinkedIn jobs for a platform-owned target."""

    source = JobSource.LINKEDIN

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        request_delay_seconds: float = _REQUEST_DELAY_SECONDS,
    ) -> None:
        self._client = client
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
            raise ValueError(f"LinkedInCollector cannot collect source {target.source.value!r}")

        logger.info(
            "linkedin_collection_started",
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
            for page in range(0, _MAX_PAGES):
                if len(collected) >= target.max_jobs:
                    break

                response = await self._fetch_search_page(
                    client,
                    target=target,
                    start=page * _DEFAULT_PAGE_SIZE,
                )

                page_jobs = self._parse_search_response(response.text)

                logger.info(
                    "linkedin_search_page_completed",
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
                    page < _MAX_PAGES - 1
                    and len(collected) < target.max_jobs
                    and self._request_delay_seconds > 0
                ):
                    await asyncio.sleep(self._request_delay_seconds)

        finally:
            if owns_client:
                await client.aclose()

        logger.info(
            "linkedin_collection_completed",
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
            raise ValueError(f"LinkedInCollector cannot collect source {target.source.value!r}")

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
                    logger.info(
                        "linkedin_job_detail_unavailable",
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
                        "linkedin_job_detail_parse_failed",
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
        """Create the HTTP client used for LinkedIn requests."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(_DEFAULT_TIMEOUT_SECONDS),
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            },
        )

    async def _fetch_search_page(
        self,
        client: httpx.AsyncClient,
        *,
        target: CollectionTarget,
        start: int,
    ) -> httpx.Response:
        """Fetch one LinkedIn search-results page."""
        params: dict[str, str | int] = {
            "keywords": target.query,
            "start": start,
            "position": 1,
            "pageNum": 0,
        }

        if target.location:
            params["location"] = target.location

        url = f"{_LINKEDIN_SEARCH_URL}?{urlencode(params)}"

        try:
            response = await client.get(url)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TemporaryCollectionError(
                f"LinkedIn request failed for query {target.query!r}"
            ) from exc

        self._raise_for_status(response, request_description="collection request")
        return response

    async def _fetch_job_detail(
        self,
        client: httpx.AsyncClient,
        *,
        external_job_id: str,
    ) -> httpx.Response:
        """Fetch one LinkedIn job-detail page."""
        url = f"{_LINKEDIN_JOB_DETAIL_URL}/{external_job_id}"

        try:
            response = await client.get(url)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TemporaryCollectionError(
                f"LinkedIn detail request failed for job {external_job_id!r}"
            ) from exc

        self._raise_for_status(response, request_description="job-detail request")
        return response

    @staticmethod
    def _raise_for_status(
        response: httpx.Response,
        *,
        request_description: str,
    ) -> None:
        """Translate HTTP failures into collection errors."""
        if response.status_code == 429:
            raise SourceRateLimitedError(
                f"LinkedIn rate limited the {request_description}",
                retry_after_seconds=60,
            )

        if response.status_code == 403 or response.status_code == 999:
            raise SourceBlockedError(
                f"LinkedIn blocked the {request_description} (code {response.status_code})",
                retry_after_seconds=300,
            )

        if response.status_code in {408, 425, 502, 503, 504}:
            raise TemporaryCollectionError(
                "LinkedIn temporarily failed the "
                f"{request_description} with HTTP {response.status_code}"
            )

        response.raise_for_status()

    def _parse_search_response(
        self,
        body: str,
    ) -> list[DiscoveredSourceJob]:
        """Parse LinkedIn search HTML into discovered jobs."""
        jobs: list[DiscoveredSourceJob] = []

        # Find <li> elements containing job links
        link_pattern = re.compile(
            r'<a[^>]+href=["\']'
            r'(?P<url>[^"\']*/jobs/view/(?P<id>\d+)[^"\']*)'
            r'["\'][^>]*>'
            r"(?P<content>.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )

        tag_pattern = re.compile(r"<[^>]+>")

        for match in link_pattern.finditer(body):
            url = match.group("url")
            external_id = match.group("id")

            if not external_id:
                continue

            # In the new LinkedIn guest UI, the title might be within spans inside the anchor,
            # or in an adjacent element. We can extract text from the anchor as a fallback.
            content = tag_pattern.sub(" ", match.group("content"))
            title = " ".join(content.split())

            if not title:
                # Sometimes the anchor is empty except for spans, or title is in a nearby h3.
                # Just use a placeholder if empty, the detail fetch will fix it.
                title = "LinkedIn Job"

            jobs.append(
                DiscoveredSourceJob(
                    source=self.source.value,
                    external_job_id=external_id,
                    title=title,
                    url=self._absolute_url(url),
                )
            )

        # Deduplicate
        seen = set()
        deduped = []
        for job in jobs:
            if job.external_job_id not in seen:
                seen.add(job.external_job_id)
                deduped.append(job)

        return deduped

    def _parse_job_detail(
        self,
        body: str,
        *,
        expected_external_job_id: str,
    ) -> RawSourceJob | None:
        """Parse one LinkedIn JobPosting detail page."""
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

            # Usually the payload is directly a JobPosting or a graph
            if payload.get("@type") == "JobPosting":
                job = self._job_from_mapping(payload, expected_external_job_id)
                if job:
                    return job

            if "@graph" in payload:
                for item in payload["@graph"]:
                    if item.get("@type") == "JobPosting":
                        job = self._job_from_mapping(item, expected_external_job_id)
                        if job:
                            return job

        return None

    def _job_from_mapping(
        self,
        value: Mapping[str, Any],
        expected_external_job_id: str,
    ) -> RawSourceJob | None:
        """Convert LinkedIn JSON-LD mapping into RawSourceJob."""
        title = value.get("title")
        if not title:
            return None

        external_id = expected_external_job_id

        url = value.get("url", "")
        description = value.get("description", "")

        # Cleanup HTML from description
        tag_pattern = re.compile(r"<[^>]+>")
        description = tag_pattern.sub(" ", description)
        description = " ".join(description.split())

        company = ""
        hiring_org = value.get("hiringOrganization", {})
        if isinstance(hiring_org, dict):
            company = hiring_org.get("name", "")

        location = ""
        job_location = value.get("jobLocation", {})
        if isinstance(job_location, dict):
            address = job_location.get("address", {})
            if isinstance(address, dict):
                parts = []
                if "addressLocality" in address:
                    parts.append(address["addressLocality"])
                if "addressRegion" in address:
                    parts.append(address["addressRegion"])
                if "addressCountry" in address:
                    parts.append(address["addressCountry"])
                location = ", ".join(parts)

        posted_at = None
        date_posted = value.get("datePosted")
        if date_posted:
            posted_at = self._parse_datetime(date_posted)

        employment_type = value.get("employmentType", "")
        if isinstance(employment_type, list):
            employment_type = employment_type[0] if employment_type else ""

        remote = None
        if "remote" in location.lower() or "remote" in title.lower():
            remote = True

        return RawSourceJob(
            source=self.source.value,
            external_job_id=external_id,
            title=title,
            company=company,
            location=location,
            url=url,
            description=description,
            salary_text=None,
            employment_type=employment_type,
            remote=remote,
            posted_at=posted_at,
            source_updated_at=None,
            skills=(),
            raw_data=dict(value),
        )

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        candidate = value.strip()
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _absolute_url(url: str) -> str:
        if url.startswith("/"):
            return f"https://www.linkedin.com{url}"
        if url.startswith("http"):
            return url
        return f"https://www.linkedin.com/{url}"
