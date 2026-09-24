"""Unit tests for the Dice global-job collector."""

from __future__ import annotations

import httpx
import pytest

from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError, SourceRateLimitedError
from app.jobs.normalization import DiscoveredSourceJob
from app.jobs.registry import build_collector_registry
from app.jobs.sources.dice import DiceCollector
from app.jobs.targets import CollectionTarget


def _target(max_jobs: int = 10) -> CollectionTarget:
    return CollectionTarget(
        source=JobSource.DICE,
        query="DevOps Engineer",
        location="United States",
        max_jobs=max_jobs,
    )


@pytest.mark.anyio
async def test_dice_collector_parses_structured_job() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "DevOps Engineer",
          "url": "https://www.dice.com/job-detail/abc123",
          "datePosted": "2026-09-22T10:00:00Z",
          "dateModified": "2026-09-23T11:00:00Z",
          "description": "Requires 2-4 years of experience.",
          "employmentType": "FULL_TIME",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "Example Technologies"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "Austin",
              "addressRegion": "TX",
              "addressCountry": "US"
            }
          },
          "skills": ["AWS", "Kubernetes", "Terraform"]
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
        collector = DiceCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.collect(_target())

    assert len(jobs) == 1

    job = jobs[0]

    assert job.source == "dice"
    assert job.external_job_id == "abc123"
    assert job.title == "DevOps Engineer"
    assert job.company == "Example Technologies"
    assert job.location == "Austin, TX, US"
    assert job.url == "https://www.dice.com/job-detail/abc123"
    assert job.description == "Requires 2-4 years of experience."
    assert job.employment_type == "FULL_TIME"
    assert job.skills == ("AWS", "Kubernetes", "Terraform")
    assert job.posted_at is not None
    assert job.source_updated_at is not None
    assert job.raw_data["url"] == "https://www.dice.com/job-detail/abc123"


@pytest.mark.anyio
async def test_dice_collector_deduplicates_results() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
        [
          {
            "@type": "JobPosting",
            "title": "DevOps Engineer",
            "url": "https://www.dice.com/job-detail/abc123"
          },
          {
            "@type": "JobPosting",
            "title": "DevOps Engineer",
            "url": "https://www.dice.com/job-detail/abc123"
          }
        ]
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
        collector = DiceCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.collect(_target())

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "abc123"


@pytest.mark.anyio
async def test_dice_collector_handles_empty_results() -> None:
    html = "<html><body>No jobs</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = DiceCollector(
            client=client,
            request_delay_seconds=0,
        )

        jobs = await collector.collect(_target())

    assert jobs == ()


@pytest.mark.anyio
async def test_dice_detail_expiry_does_not_discard_other_results() -> None:
    valid = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"DevOps Engineer",
     "url":"https://www.dice.com/job-detail/valid"}
    </script>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/expired"):
            return httpx.Response(404, request=request)
        return httpx.Response(200, text=valid, request=request)

    candidates = (
        DiscoveredSourceJob("dice", "expired", "Expired"),
        DiscoveredSourceJob("dice", "valid", "DevOps Engineer"),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await DiceCollector(client=client, request_delay_seconds=0).fetch_details(
            _target(), candidates
        )

    assert [job.external_job_id for job in jobs] == ["valid"]


@pytest.mark.anyio
async def test_dice_429_raises_rate_limited_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "120"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = DiceCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceRateLimitedError) as exc_info:
            await collector.collect(_target())

    assert exc_info.value.retry_after_seconds == 120


@pytest.mark.anyio
async def test_dice_403_raises_blocked_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = DiceCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceBlockedError):
            await collector.collect(_target())


def test_dice_collector_is_registered() -> None:
    registry = build_collector_registry()

    assert registry.is_registered(JobSource.DICE)

    collector = registry.resolve(JobSource.DICE)

    assert collector.source is JobSource.DICE
