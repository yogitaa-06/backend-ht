"""Unit tests for the LinkedIn global-job collector."""

from __future__ import annotations

import httpx
import pytest

from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError, SourceRateLimitedError
from app.jobs.normalization import DiscoveredSourceJob
from app.jobs.registry import build_collector_registry
from app.jobs.sources.linkedin import LinkedInCollector
from app.jobs.targets import CollectionTarget


def _target(max_jobs: int = 10) -> CollectionTarget:
    return CollectionTarget(
        source=JobSource.LINKEDIN,
        query="Python Developer",
        location="United States",
        max_jobs=max_jobs,
    )


@pytest.mark.anyio
async def test_linkedin_collector_parses_structured_job() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
        {
          "@context": "http://schema.org",
          "@type": "JobPosting",
          "title": "Python Developer",
          "url": "https://www.linkedin.com/jobs/view/123456789",
          "datePosted": "2026-09-22T10:00:00.000Z",
          "description": "Requires 2-4 years of experience.",
          "employmentType": ["FULL_TIME"],
          "hiringOrganization": {
            "@type": "Organization",
            "name": "Example Tech"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "Austin",
              "addressRegion": "TX",
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
        collector = LinkedInCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.fetch_details(
            _target(),
            [DiscoveredSourceJob(JobSource.LINKEDIN.value, "123456789", "Python Developer")]
        )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.source == "linkedin"
    assert job.external_job_id == "123456789"
    assert job.title == "Python Developer"
    assert job.company == "Example Tech"
    assert job.location == "Austin, TX, US"
    assert job.url == "https://www.linkedin.com/jobs/view/123456789"
    assert job.description == "Requires 2-4 years of experience."
    assert job.employment_type == "FULL_TIME"
    assert job.remote is None
    assert job.posted_at is not None
    assert job.raw_data["url"] == "https://www.linkedin.com/jobs/view/123456789"


@pytest.mark.anyio
async def test_linkedin_collector_deduplicates_results() -> None:
    html = """
    <html>
      <body>
        <ul class="jobs-search__results-list">
          <li>
            <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123456789">
              Python Developer
            </a>
          </li>
          <li>
            <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123456789">
              Python Developer
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
        collector = LinkedInCollector(
            client=client,
            request_delay_seconds=0,
        )
        jobs = await collector.discover(_target())

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "123456789"


@pytest.mark.anyio
async def test_linkedin_collector_handles_empty_results() -> None:
    html = "<html><body>No jobs</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = LinkedInCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.discover(_target())

    assert jobs == ()


@pytest.mark.anyio
async def test_linkedin_429_raises_rate_limited_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = LinkedInCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceRateLimitedError):
            await collector.discover(_target())


@pytest.mark.anyio
async def test_linkedin_403_raises_blocked_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = LinkedInCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceBlockedError):
            await collector.discover(_target())


def test_linkedin_collector_is_registered() -> None:
    registry = build_collector_registry()
    assert registry.is_registered(JobSource.LINKEDIN)
    collector = registry.resolve(JobSource.LINKEDIN)
    assert collector.source is JobSource.LINKEDIN
