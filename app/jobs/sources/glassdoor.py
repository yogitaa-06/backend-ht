"""Glassdoor global-job collector.

This module contains Glassdoor-specific HTTP and parsing behavior only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

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

_GLASSDOOR_SEARCH_URL = "https://www.glassdoor.com/Job/jobs.htm"
_GLASSDOOR_JOB_DETAIL_URL = "https://www.glassdoor.com/job-listing/job"

_DEFAULT_TIMEOUT_SECONDS = 20.0
_MAX_PAGES = 5
_REQUEST_DELAY_SECONDS = 3.0

CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "cf_chl_",
    "cf-chl-",
    "challenge-platform",
    "challenges.cloudflare.com",
    "cf-turnstile",
    "just a moment...",
    "attention required! | cloudflare",
    "datadome",
    "geo.captcha-delivery.com",
    "px-captcha",
    "_pxhd",
    "perimeterx",
    "g-recaptcha",
    "h-captcha",
    "hcaptcha.com",
    "are you a robot",
    "verify you are human",
    "unusual traffic from your computer network",
    "access to this page has been denied",
    "help us protect glassdoor",
    "security check to access",
    "<title>just a moment",
    "<title>security | glassdoor",
    "<title>attention required",
)


class GlassdoorCollector:
    """Collect recent public Glassdoor jobs for a platform-owned target."""

    source = JobSource.GLASSDOOR

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | Any | None = None,
        request_delay_seconds: float = _REQUEST_DELAY_SECONDS,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._request_delay_seconds = request_delay_seconds
        self._cache: dict[str, RawSourceJob] = {}

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
            raise ValueError(f"GlassdoorCollector cannot collect source {target.source.value!r}")

        logger.info(
            "glassdoor_collection_started",
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

        loc_id, loc_type, loc_name = 0, "C", target.location or ""
        if target.location and target.location.lower() != "remote":
            loc_id, loc_type, loc_name = await self._resolve_location(client, target.location)

        try:
            for page in range(1, _MAX_PAGES + 1):
                if len(collected) >= target.max_jobs:
                    break

                response = await self._fetch_search_page(
                    client,
                    target=target,
                    page=page,
                    loc_id=loc_id,
                    loc_type=loc_type,
                    loc_name=loc_name,
                )

                discovered_jobs, raw_jobs = self._parse_search_response(response.text)

                logger.info(
                    "glassdoor_search_page_completed",
                    extra={
                        "source": self.source.value,
                        "query": target.query,
                        "location": target.location,
                        "page": page,
                        "jobs_on_page": len(discovered_jobs),
                    },
                )

                if not discovered_jobs:
                    logger.info("glassdoor_empty_results", extra={"source": self.source.value})
                    break

                new_on_page = 0

                for d_job, r_job in zip(discovered_jobs, raw_jobs, strict=False):
                    if d_job.external_job_id in seen_ids:
                        continue

                    seen_ids.add(d_job.external_job_id)
                    collected.append(d_job)
                    self._cache[d_job.external_job_id] = r_job
                    new_on_page += 1

                    if len(collected) >= target.max_jobs:
                        break

                if new_on_page == 0:
                    break

                if (
                    page < _MAX_PAGES
                    and len(collected) < target.max_jobs
                    and self._request_delay_seconds > 0
                ):
                    await asyncio.sleep(self._request_delay_seconds)

        finally:
            if owns_client:
                if hasattr(client, "aclose"):
                    await client.aclose()
                elif hasattr(client, "close"):
                    res = client.close()
                    if asyncio.iscoroutine(res):
                        await res

        logger.info(
            "glassdoor_collection_completed",
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
        """Return the pre-parsed RawSourceJob objects for the requested candidates."""
        if target.source is not self.source:
            raise ValueError(f"GlassdoorCollector cannot collect source {target.source.value!r}")

        collected: list[RawSourceJob] = []

        for candidate in candidates:
            cached = self._cache.get(candidate.external_job_id)
            if cached:
                collected.append(cached)
            else:
                logger.warning(
                    "glassdoor_job_detail_unavailable",
                    extra={
                        "source": self.source.value,
                        "external_job_id": candidate.external_job_id,
                    },
                )

        return tuple(collected)

    def _build_client(self) -> Any:
        """Create the HTTP client used for Glassdoor requests with Chrome TLS impersonation."""
        proxy_url = (
            self._settings.job_collection_proxy_url.get_secret_value()
            if self._settings.job_collection_proxy_url
            else None
        )
        try:
            from curl_cffi.requests import AsyncSession

            proxies: Any = {"http": proxy_url, "https": proxy_url} if proxy_url else None
            impersonate = getattr(self._settings, "glassdoor_impersonate", "chrome124")
            return AsyncSession(
                impersonate=impersonate,
                proxies=proxies,
                timeout=int(_DEFAULT_TIMEOUT_SECONDS),
            )
        except Exception as exc:
            logger.warning("glassdoor_curl_cffi_fallback_to_httpx", extra={"error": str(exc)})
            return build_collection_client(self._settings, timeout_seconds=_DEFAULT_TIMEOUT_SECONDS)

    async def _resolve_location(self, client: Any, location: str) -> tuple[int, str, str]:
        text = location.strip()
        # Fast path bypass: The reference project uses locId=0 and locT=C for all locations
        # and lets the search endpoint resolve it server-side.
        return 0, "C", text

    async def _fetch_search_page(
        self,
        client: Any,
        *,
        target: CollectionTarget,
        page: int,
        loc_id: int,
        loc_type: str,
        loc_name: str,
    ) -> Any:
        """Fetch one Glassdoor search-results page."""
        params: dict[str, str | int] = {
            "sc.keyword": target.query,
            "p": page,
        }

        if target.location and target.location.lower() != "remote":
            params["locT"] = loc_type
            params["locId"] = loc_id
            params["locKeyword"] = loc_name

        url = f"{_GLASSDOOR_SEARCH_URL}?{urlencode(params)}"

        attempts = 5
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            if attempt > 1:
                await asyncio.sleep(0.5)

            try:
                # Force Connection: close so rotating proxies assign a new IP
                response = await client.get(url, headers={"Connection": "close"})
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                continue
            except Exception as exc:
                if "curl" in type(exc).__module__.lower() or "RequestsError" in type(exc).__name__:
                    last_exc = exc
                    continue
                raise

            try:
                self._raise_for_status(response, request_description="collection request")
                return response
            except (SourceBlockedError, SourceRateLimitedError, TemporaryCollectionError) as exc:
                last_exc = exc
                continue

        # Exhausted attempts
        if last_exc:
            is_net_error = (
                isinstance(last_exc, (httpx.TimeoutException, httpx.NetworkError))
                or "curl" in type(last_exc).__module__.lower()
            )
            if is_net_error:
                raise TemporaryCollectionError(
                    f"Glassdoor request failed for query {target.query!r} after {attempts} attempts"
                ) from last_exc
            raise last_exc

        raise SourceBlockedError("Glassdoor request failed entirely")

    def _raise_for_status(
        self,
        response: Any,
        *,
        request_description: str,
    ) -> None:
        """Translate HTTP failures into collection errors."""
        status = getattr(response, "status_code", 0)
        text = getattr(response, "text", "") or ""

        blocked = False
        if status in {403, 407, 429, 999}:
            blocked = True
        else:
            scan_head = text[:5000].lower()
            for marker in CHALLENGE_MARKERS:
                if marker in scan_head:
                    blocked = True
                    break
            if (
                not blocked
                and status == 200
                and len(text.strip()) < 512
                and ("<html" in scan_head or "<!doctype" in scan_head)
                and "jobview" not in text
            ):
                blocked = True

        if blocked:
            logger.info("glassdoor_collection_blocked", extra={"status": status})
            if status == 429:
                raise SourceRateLimitedError(
                    f"Glassdoor rate limited the {request_description}",
                    retry_after_seconds=60,
                )
            raise SourceBlockedError(
                f"Glassdoor blocked the {request_description} (code {status})",
                retry_after_seconds=300,
            )

        if status in {408, 425, 502, 503, 504}:
            raise TemporaryCollectionError(
                f"Glassdoor temporarily failed the {request_description} with HTTP {status}"
            )

        response.raise_for_status()

    def _parse_search_response(
        self, body: str
    ) -> tuple[list[DiscoveredSourceJob], list[RawSourceJob]]:
        """Parse Glassdoor search HTML chunks into discovered and raw jobs."""
        chunks = re.findall(r"self\.__next_f\.push\(\[1,\s*\"(.*?)\"\]\)", body)
        if not chunks:
            # Fallback legacy parsing just in case it returns plain HTML
            return self._legacy_parse(body)

        def _replace_unicode(m: re.Match[str]) -> str:
            try:
                return chr(int(m.group(1), 16))
            except ValueError:
                return m.group(0)

        raw = "".join(chunks)
        text = re.sub(r"\\u([0-9a-fA-F]{4})", _replace_unicode, raw)
        text = (
            text.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n").replace("\\t", "\t")
        )

        parts = text.split('"jobview":')[1:]
        discovered = []
        raw_jobs = []
        seen = set()

        for p in parts:
            title_m = re.search(r'"jobTitleText":\s*"([^"]+)"', p)
            comp_m = re.search(r'"employerNameFromSearch":\s*"([^"]+)"', p)
            link_m = re.search(r'"seoJobLink":\s*"([^"]+)"', p)
            loc_m = re.search(r'"locationName":\s*"([^"]+)"', p)
            salary_min_m = re.search(r'"p10":\s*(\d+)', p)
            salary_max_m = re.search(r'"p90":\s*(\d+)', p)

            if not (title_m and comp_m and link_m):
                continue

            title = title_m.group(1).strip()
            comp = comp_m.group(1).strip()
            link = link_m.group(1).strip()
            clean_link = f"https://www.glassdoor.com{link}" if link.startswith("/") else link

            jl_match = re.search(r"jl=(\d+)", link)
            ext_id = jl_match.group(1) if jl_match else ""
            if not ext_id:
                listing_id_m = re.search(r'"listingId":\s*(\d+)', p)
                if listing_id_m:
                    ext_id = listing_id_m.group(1)
                else:
                    continue

            if ext_id in seen:
                continue
            seen.add(ext_id)

            loc = loc_m.group(1).strip() if loc_m else ""
            smin = int(salary_min_m.group(1)) if salary_min_m else None
            smax = int(salary_max_m.group(1)) if salary_max_m else None

            desc = f"{title} opportunity at {comp} in {loc or 'USA'}."
            desc_m = re.search(r'"descriptionFragmentsText":\s*(\[[^\]]*\])', p)
            if desc_m:
                with contextlib.suppress(Exception):
                    frags = json.loads(desc_m.group(1))
                    if isinstance(frags, list) and frags:
                        tag_pattern = re.compile(r"<[^>]+>")
                        desc = " ".join(
                            tag_pattern.sub(" ", str(f)).strip() for f in frags if f
                        ).strip()

            age_m = re.search(r'"ageInDays":\s*(\d+)', p)
            posted_at = None
            if age_m:
                try:
                    posted_at = datetime.now(UTC) - timedelta(days=int(age_m.group(1)))
                except (ValueError, TypeError):
                    pass

            comb_text = f"{title} {loc or ''} {desc}".lower()
            remote = None
            if "remote" in comb_text or "work from home" in comb_text:
                remote = True
            elif "onsite" in comb_text or "hybrid" in comb_text:
                remote = False

            salary_text = None
            if smin and smax:
                salary_text = f"${smin} - ${smax}"

            discovered.append(
                DiscoveredSourceJob(
                    source=self.source.value,
                    external_job_id=ext_id,
                    title=title,
                    url=clean_link,
                )
            )

            raw_jobs.append(
                RawSourceJob(
                    source=self.source.value,
                    external_job_id=ext_id,
                    title=title,
                    company=comp,
                    location=loc,
                    url=clean_link,
                    description=desc,
                    salary_text=salary_text,
                    employment_type=None,
                    remote=remote,
                    posted_at=posted_at,
                    source_updated_at=None,
                    raw_data={
                        "title": title,
                        "company": comp,
                        "url": clean_link,
                        "salary_min": smin,
                        "salary_max": smax,
                        "salary_currency": "USD",
                    },
                )
            )

        if not discovered:
            logger.warning("glassdoor_unexpected_response", extra={"source": self.source.value})

        return discovered, raw_jobs

    def _legacy_parse(self, body: str) -> tuple[list[DiscoveredSourceJob], list[RawSourceJob]]:
        # Fallback empty parse
        return [], []
