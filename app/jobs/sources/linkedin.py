"""LinkedIn global-job collector.

This module contains LinkedIn-specific HTTP and parsing behavior only.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import urlencode, urlparse

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
                    job_url=candidate.url,
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
        return build_collection_client(self._settings, timeout_seconds=_DEFAULT_TIMEOUT_SECONDS)

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

        chunks = re.split(r"(?i)<li[^>]*>", body)
        tag_pattern = re.compile(r"<[^>]+>")

        for chunk in chunks:
            if "/jobs/view/" not in chunk:
                continue

            link_match = re.search(
                r'<a[^>]+href=["\']([^"\']*/jobs/view/[^"\']*)["\']', chunk, re.IGNORECASE
            )
            if not link_match:
                continue

            raw_url = link_match.group(1)
            parsed_url = urlparse(raw_url)
            clean_url = self._absolute_url(parsed_url.path)

            urn_match = re.search(
                r'data-entity-urn=["\']urn:li:jobPosting:(\d+)["\']', chunk, re.IGNORECASE
            )
            if urn_match:
                external_id = urn_match.group(1)
            else:
                id_match = re.search(r"(?:-|/)(\d+)/?$", parsed_url.path)
                if id_match:
                    external_id = id_match.group(1)
                else:
                    logger.warning(
                        "linkedin_invalid_job_url_skipped",
                        extra={
                            "source": self.source.value,
                            "url": raw_url,
                            "path": parsed_url.path,
                        },
                    )
                    continue

            title_match = re.search(
                r"<h3[^>]*base-search-card__title[^>]*>(.*?)</h3>", chunk, re.IGNORECASE | re.DOTALL
            )
            if title_match:
                title_raw = title_match.group(1)
            else:
                title_match_a = re.search(
                    r'<a[^>]+href=["\'][^"\']*["\'][^>]*>(.*?)</a>',
                    chunk,
                    re.IGNORECASE | re.DOTALL,
                )
                title_raw = title_match_a.group(1) if title_match_a else "LinkedIn Job"

            title = " ".join(tag_pattern.sub(" ", title_raw).split())

            jobs.append(
                DiscoveredSourceJob(
                    source=self.source.value,
                    external_job_id=external_id,
                    title=title,
                    url=clean_url,
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
        job_url: str | None,
    ) -> RawSourceJob | None:
        """Parse one LinkedIn JobPosting detail page."""
        title_match = re.search(
            r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            return None
        title = title_match.group(1).strip()

        company = ""
        company_match = re.search(
            r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if not company_match:
            company_match = re.search(
                r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>',
                body,
                re.IGNORECASE | re.DOTALL,
            )
        if company_match:
            company = company_match.group(1).strip()

        location = ""
        location_matches = re.findall(
            r'<span[^>]*class="[^"]*topcard__flavor topcard__flavor--bullet'
            r'[^"]*"[^>]*>(.*?)</span>',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if location_matches:
            location = location_matches[0].strip()

        description = ""
        desc_match = re.search(
            r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if not desc_match:
            desc_match = re.search(
                r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>',
                body,
                re.IGNORECASE | re.DOTALL,
            )
        if desc_match:
            desc_raw = desc_match.group(1)
            tag_pattern = re.compile(r"<[^>]+>")
            description = tag_pattern.sub(" ", desc_raw)
            description = " ".join(description.split())

        criteria = {}
        for item in re.finditer(
            r'<li[^>]*class="[^"]*description__job-criteria-item[^"]*"[^>]*>(.*?)</li>',
            body,
            re.IGNORECASE | re.DOTALL,
        ):
            inner = item.group(1)
            h_match = re.search(
                r"<h3[^>]*description__job-criteria-subheader[^>]*>(.*?)</h3>",
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            v_match = re.search(
                r"<span[^>]*description__job-criteria-text[^>]*>(.*?)</span>",
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            if h_match and v_match:
                hdr = " ".join(re.sub(r"<[^>]+>", " ", h_match.group(1)).split()).lower()
                val = " ".join(re.sub(r"<[^>]+>", " ", v_match.group(1)).split())
                criteria[hdr] = val

        employment_type = criteria.get("employment type", "")

        remote = None
        if "remote" in location.lower() or "remote" in title.lower():
            remote = True

        return RawSourceJob(
            source=self.source.value,
            external_job_id=expected_external_job_id,
            title=title,
            company=company,
            location=location,
            url=job_url,
            description=description,
            salary_text=None,
            employment_type=employment_type,
            remote=remote,
            posted_at=None,
            source_updated_at=None,
            skills=(),
            raw_data={"criteria": criteria},
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
