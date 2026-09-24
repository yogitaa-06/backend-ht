"""Unit tests for the Glassdoor global-job collector."""

from __future__ import annotations

import httpx
import pytest

from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError, SourceRateLimitedError
from app.jobs.normalization import DiscoveredSourceJob
from app.jobs.registry import build_collector_registry
from app.jobs.sources.glassdoor import GlassdoorCollector
from app.jobs.targets import CollectionTarget


def _target(max_jobs: int = 10) -> CollectionTarget:
    return CollectionTarget(
        source=JobSource.GLASSDOOR,
        query="Data Scientist",
        location="New York",
        max_jobs=max_jobs,
    )


@pytest.mark.anyio
async def test_glassdoor_collector_parses_structured_job() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Data Scientist",
          "url": "https://www.glassdoor.com/job-listing/job?jl=987654321",
          "datePosted": "2026-09-22T10:00:00.000Z",
          "description": "Requires machine learning expertise.",
          "employmentType": "FULL_TIME",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "Data Co"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "New York",
              "addressRegion": "NY",
              "addressCountry": "US"
            }
          }
        }
        </script>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.fetch_details(
            _target(),
            [DiscoveredSourceJob(JobSource.GLASSDOOR.value, "987654321", "Data Scientist")]
        )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.source == "glassdoor"
    assert job.external_job_id == "987654321"
    assert job.title == "Data Scientist"
    assert job.company == "Data Co"
    assert job.location == "New York, NY, US"
    assert job.url == "https://www.glassdoor.com/job-listing/job?jl=987654321"
    assert job.description == "Requires machine learning expertise."
    assert job.employment_type == "FULL_TIME"
    assert job.posted_at is not None
    assert job.raw_data["url"] == "https://www.glassdoor.com/job-listing/job?jl=987654321"


@pytest.mark.anyio
async def test_glassdoor_collector_deduplicates_results() -> None:
    html = """
    <html>
      <body>
        <ul>
          <li>
            <a href="https://www.glassdoor.com/job-listing/job?jl=987654321">
              Data Scientist
            </a>
          </li>
          <li>
            <a href="https://www.glassdoor.com/job-listing/job?jl=987654321">
              Data Scientist
            </a>
          </li>
        </ul>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )
        jobs = await collector.discover(_target())

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "987654321"


@pytest.mark.anyio
async def test_glassdoor_collector_handles_empty_results() -> None:
    html = "<html><body>No jobs</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.discover(_target())

    assert jobs == ()


@pytest.mark.anyio
async def test_glassdoor_429_raises_rate_limited_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceRateLimitedError):
            await collector.discover(_target())


@pytest.mark.anyio
async def test_glassdoor_403_raises_blocked_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceBlockedError):
            await collector.discover(_target())


def test_glassdoor_collector_is_registered() -> None:
    registry = build_collector_registry()
    assert registry.is_registered(JobSource.GLASSDOOR)
    collector = registry.resolve(JobSource.GLASSDOOR)
    assert collector.source is JobSource.GLASSDOOR
