"""Unit tests for the Glassdoor global-job collector."""

from __future__ import annotations

import httpx
import pytest

from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError, SourceRateLimitedError
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
    html = (
        "<html>\n"
        "  <body><!-- " + " " * 600 + " -->\n"
        '    <script>self.__next_f.push([1, "{\\"jobview\\": {\\"jobTitleText\\": '
        '\\"Data Scientist\\", \\"employerNameFromSearch\\": \\"Data Co\\", '
        '\\"seoJobLink\\": \\"/job-listing/job?jl=987654321\\", \\"locationName\\": '
        '\\"New York, NY\\", \\"listingId\\": 987654321, \\"p10\\": 100000, '
        '\\"p90\\": 150000, \\"ageInDays\\": 2, \\"descriptionFragmentsText\\": '
        '[\\"Requires machine learning expertise.\\"]}}"])</script>\n'
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
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )

        # Discover will fetch the page, parse jobs, and cache raw jobs
        discovered = await collector.discover(_target())
        jobs = await collector.fetch_details(_target(), discovered)

    assert len(jobs) == 1

    job = jobs[0]

    assert job.source == "glassdoor"
    assert job.external_job_id == "987654321"
    assert job.title == "Data Scientist"
    assert job.company == "Data Co"
    assert job.location == "New York, NY"
    assert job.url == "https://www.glassdoor.com/job-listing/job?jl=987654321"
    assert job.description == "Requires machine learning expertise."
    assert job.salary_text == "$100000 - $150000"
    assert job.posted_at is not None
    assert job.raw_data["url"] == "https://www.glassdoor.com/job-listing/job?jl=987654321"
    assert job.raw_data["salary_min"] == 100000
    assert job.raw_data["salary_max"] == 150000
    assert job.raw_data["salary_currency"] == "USD"


@pytest.mark.anyio
async def test_glassdoor_collector_deduplicates_results() -> None:
    html = (
        "<html>\n"
        "  <body><!-- " + " " * 600 + " -->\n"
        '    <script>self.__next_f.push([1, "{\\"jobview\\": {\\"jobTitleText\\": '
        '\\"Data Scientist\\", \\"employerNameFromSearch\\": \\"Data Co\\", '
        '\\"seoJobLink\\": \\"/job-listing/job?jl=987654321\\", \\"locationName\\": '
        '\\"New York, NY\\", \\"listingId\\": 987654321}}"])</script>\n'
        '    <script>self.__next_f.push([1, "{\\"jobview\\": {\\"jobTitleText\\": '
        '\\"Data Scientist\\", \\"employerNameFromSearch\\": \\"Data Co\\", '
        '\\"seoJobLink\\": \\"/job-listing/job?jl=987654321\\", \\"locationName\\": '
        '\\"New York, NY\\", \\"listingId\\": 987654321}}"])</script>\n'
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
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )
        jobs = await collector.discover(_target())

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "987654321"


@pytest.mark.anyio
async def test_glassdoor_collector_handles_empty_results() -> None:
    html = "<html><body><!-- " + " " * 600 + " -->No jobs</body></html>"

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


@pytest.mark.anyio
async def test_glassdoor_challenge_raises_blocked_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html><body>cf-browser-verification</body></html>", request=request
        )

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


@pytest.mark.anyio
async def test_glassdoor_html_title_challenge_raises_blocked_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "<html><head><title>Just a moment...</title></head>"
                "<body>Verify you are human</body></html>"
            ),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GlassdoorCollector(
            client=client,
            request_delay_seconds=0,
        )

        with pytest.raises(SourceBlockedError):
            await collector.discover(_target())


def test_glassdoor_collector_builds_curl_cffi_client() -> None:
    collector = GlassdoorCollector()
    client = collector._build_client()
    try:
        from curl_cffi.requests import AsyncSession

        assert isinstance(client, AsyncSession)
    finally:
        import asyncio

        if hasattr(client, "close"):
            res = client.close()
            if asyncio.iscoroutine(res):
                asyncio.run(res)
