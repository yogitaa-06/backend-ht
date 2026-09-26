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
        <h2 class="top-card-layout__title">Python Developer</h2>
        <a class="topcard__org-name-link">Example Tech</a>
        <span class="topcard__flavor topcard__flavor--bullet">Austin, TX, US</span>
        <div class="show-more-less-html__markup">Requires 2-4 years of experience.</div>
        <ul>
            <li class="description__job-criteria-item">
                <h3 class="description__job-criteria-subheader">Employment type</h3>
                <span class="description__job-criteria-text">FULL_TIME</span>
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

        jobs = await collector.fetch_details(
            _target(),
            [
                DiscoveredSourceJob(
                    JobSource.LINKEDIN.value,
                    "123456789",
                    "Python Developer",
                    "https://www.linkedin.com/jobs/view/123456789",
                )
            ],
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
    assert job.posted_at is None
    assert "criteria" in job.raw_data


@pytest.mark.anyio
async def test_linkedin_collector_deduplicates_results(caplog: pytest.LogCaptureFixture) -> None:
    html = (
        "<html>\n"
        "  <body>\n"
        '    <ul class="jobs-search__results-list">\n'
        "      <!-- Case 0: data-entity-urn present -->\n"
        '      <li data-entity-urn="urn:li:jobPosting:9999999999"><a class="base-card__full-link" '
        'href="/jobs/view/something-9999999999">Job 0</a></li>\n'
        "      <!-- Case 1: Plain ID -->\n"
        '      <li><a class="base-card__full-link" href="/jobs/view/4419969671">Job 1</a></li>\n'
        "      <!-- Case 2: Slug with ID -->\n"
        '      <li><a class="base-card__full-link" '
        'href="/jobs/view/senior-software-engineer-at-company-4419969671">Job 2</a></li>\n'
        "      <!-- Case 3: Absolute URL with query params -->\n"
        '      <li><a class="base-card__full-link" '
        'href="https://www.linkedin.com/jobs/view/software-engineer-at-company-4419969671"\n'
        ' "?position=2&pageNum=0">Job 3</a></li>\n'
        "      <!-- Case 4: Query parameter shouldn't become ID -->\n"
        '      <li><a class="base-card__full-link" '
        'href="/jobs/view/some-job-4419969672?position=2">Job 4</a></li>\n'
        "      <!-- Case 5: Malformed URL without valid trailing ID -->\n"
        '      <li><a class="base-card__full-link" '
        'href="/jobs/view/bad-url-no-id">Job 5</a></li>\n'
        "      <!-- Deduplication: same ID as Job 1 -->\n"
        '      <li><a class="base-card__full-link" '
        'href="/jobs/view/duplicate-job-4419969671">Duplicate</a></li>\n'
        "    </ul>\n"
        "  </body>\n"
        "</html>"
    )

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

    # ID extracted should be 9999999999, 4419969671 and 4419969672.
    assert len(jobs) == 3
    assert jobs[0].external_job_id == "9999999999"
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/something-9999999999"

    assert jobs[1].external_job_id == "4419969671"
    assert jobs[1].url == "https://www.linkedin.com/jobs/view/4419969671"

    assert jobs[2].external_job_id == "4419969672"
    assert jobs[2].url == "https://www.linkedin.com/jobs/view/some-job-4419969672"

    # Check warning for malformed
    assert "linkedin_invalid_job_url_skipped" in caplog.text


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
