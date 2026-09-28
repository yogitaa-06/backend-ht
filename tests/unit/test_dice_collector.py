"""Unit tests for the Dice global-job collector."""

from __future__ import annotations

import json
from decimal import Decimal

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
          "isRemote": false,
          "baseSalary": {
            "currency": "USD",
            "value": {"minValue": 120000, "maxValue": 150000, "unitText": "YEAR"}
          },
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
    assert job.salary_text == "USD 120000 - 150000 per year"
    assert job.salary_min == Decimal("120000")
    assert job.salary_max == Decimal("150000")
    assert job.salary_currency == "USD"
    assert job.salary_period == "year"
    assert job.employment_type == "FULL_TIME"
    assert job.remote is False
    assert job.skills == ("AWS", "Kubernetes", "Terraform")
    assert job.experience_min_years == 2
    assert job.experience_max_years == 4
    assert job.experience_text == "2-4 years"
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


@pytest.mark.anyio
async def test_dice_collector_parses_flight_push_chunks() -> None:
    push_data = (
        'some-prefix:{"jobList":{"data":[{"guid":"11111111-2222-3333-4444-555555555555",'
        '"title":"Senior Python Developer",'
        '"detailsPageUrl":"https://www.dice.com/job-detail/11111111-2222-3333-4444-555555555555"}]}}'
    )
    html = f"""
    <html>
      <body>
        <script>
          self.__next_f.push([1, {json.dumps(push_data)}]);
        </script>
      </body>
    </html>
    """
    collector = DiceCollector(request_delay_seconds=0)
    discovered = collector._parse_search_response(html)

    assert len(discovered) == 1
    assert discovered[0].external_job_id == "11111111-2222-3333-4444-555555555555"
    assert discovered[0].title == "Senior Python Developer"


@pytest.mark.anyio
async def test_dice_collector_parses_guid_fallback() -> None:
    html = """
    <html>
      <body>
        <a href="/job-detail/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">Apply Now</a>
      </body>
    </html>
    """
    collector = DiceCollector(request_delay_seconds=0)
    discovered = collector._parse_search_response(html)

    assert len(discovered) == 1
    assert discovered[0].external_job_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.anyio
async def test_dice_collector_extracts_all_required_fields_from_description() -> None:
    payload = {
        "@type": "JobPosting",
        "title": "Senior Python Backend Engineer",
        "url": "https://www.dice.com/job-detail/test-desc-123",
        "description": (
            "We are seeking a Python developer with 3-5 years of experience in "
            "FastAPI and PostgreSQL. Compensation: $140,000 - $180,000 per year. "
            "This is a full-time remote role."
        ),
        "hiringOrganization": {"name": "Acme Corp"},
        "jobLocation": {"address": {"addressLocality": "New York", "addressRegion": "NY"}},
    }
    html = f"""
    <html>
      <body>
        <script type="application/ld+json">
        {json.dumps(payload)}
        </script>
      </body>
    </html>
    """
    collector = DiceCollector(request_delay_seconds=0)
    job = collector._parse_job_detail(html, expected_external_job_id="test-desc-123")
    assert job is not None
    assert job.title == "Senior Python Backend Engineer"
    assert job.company == "Acme Corp"
    assert job.location == "New York, NY"
    assert job.salary_min == Decimal("140000")
    assert job.salary_max == Decimal("180000")
    assert job.salary_currency == "USD"
    assert job.salary_period == "year"
    assert job.experience_min_years == 3
    assert job.experience_max_years == 5
    assert job.experience_text == "3-5 years"
    assert job.employment_type == "full-time"
    assert job.remote_type == "remote"
    assert job.remote is True
    assert set(job.skills) >= {"Python", "FastAPI", "PostgreSQL"}


@pytest.mark.anyio
async def test_dice_collector_handles_single_salary_and_plus_experience() -> None:
    payload = {
        "@type": "JobPosting",
        "title": "Staff DevOps Architect",
        "url": "https://www.dice.com/job-detail/test-plus-456",
        "description": (
            "Looking for 5+ years of experience with Docker, AWS and Terraform. "
            "Salary: $150,000 annually. Contract position."
        ),
        "hiringOrganization": {"name": "CloudWorks"},
        "jobLocation": {"address": {"addressLocality": "Austin", "addressRegion": "TX"}},
    }
    html = f"""
    <html>
      <body>
        <script type="application/ld+json">
        {json.dumps(payload)}
        </script>
      </body>
    </html>
    """
    collector = DiceCollector(request_delay_seconds=0)
    job = collector._parse_job_detail(html, expected_external_job_id="test-plus-456")
    assert job is not None
    assert job.salary_min == Decimal("150000")
    assert job.salary_max == Decimal("150000")
    assert job.salary_period == "year"
    assert job.experience_min_years == 5
    assert job.experience_max_years is None
    assert job.experience_text == "5+ years"
    assert job.employment_type == "contract"
    assert set(job.skills) >= {"Docker", "AWS", "Terraform"}


@pytest.mark.anyio
async def test_dice_collector_handles_missing_salary_gracefully() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "title": "Software Engineer",
          "url": "https://www.dice.com/job-detail/test-nosalary-789",
          "description": "Join our growing team. Competitive benefits.",
          "hiringOrganization": { "name": "Startup Inc" }
        }
        </script>
      </body>
    </html>
    """
    collector = DiceCollector(request_delay_seconds=0)
    job = collector._parse_job_detail(html, expected_external_job_id="test-nosalary-789")
    assert job is not None
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.salary_text is None
    assert job.salary_period is None
    assert job.experience_min_years is None
    assert job.experience_max_years is None
    assert job.experience_text is None
