# Scrapers Documentation

This document provides a detailed overview of all job‑source collectors implemented in the **HireAndTech** backend, the fields they extract, error‑handling behavior, and guidelines for adding new scrapers.

---
## Table of Contents
1. [Collector Interface](#collector-interface)
2. [Implemented Sources](#implemented-sources)
   - [Dice](#dice)
   - [Glassdoor](#glassdoor)
   - [LinkedIn](#linkedin)
   - [HiringCafe](#hiringcafe)
3. [Error Types](#error-types)
4. [Adding a New Scraper](#adding-a-new-scraper)
5. [Testing Scrapers](#testing-scrapers)
---
## Collector Interface
All collectors conform to the **`JobSourceCollector`** protocol defined in `app/jobs/registry.py`.

```python
class JobSourceCollector(Protocol):
    source: JobSource  # Enum identifying the source

    def discover(self, target: CollectionTarget) -> Sequence[DiscoveredSourceJob]: ...
    def fetch_details(
        self, target: CollectionTarget, candidates: Sequence[DiscoveredSourceJob]
    ) -> Sequence[RawSourceJob]: ...
```
* `discover` returns lightweight candidates (IDs, titles, URLs) limited by `target.max_jobs`.
* `fetch_details` receives a filtered list of candidates and returns fully populated `RawSourceJob` objects.
* Collectors may also expose a single‑method `collect` for legacy adapters; the coordinator detects and adapts.

Both methods raise the custom exceptions in `app/jobs/errors.py` to signal temporary or permanent failures.
---
## Implemented Sources
### Dice (`app/jobs/sources/dice.py`)
* **Discovery** – Sends an HTTP GET request to Dice's public search endpoint, parses JSON to build `DiscoveredSourceJob` objects.
* **Detail Fetch** – Requests the job URL, extracts JSON‑LD, then maps fields to `RawSourceJob`.
* **Extracted Fields**
  * `title`, `company`, `location`
  * `description`, `salary_text`
  * `employment_type`, `remote`
  * `skills` (list of strings)
  * `posted_at` (parsed from ISO date)
* **Error Handling** – Network time‑outs raise `TemporaryCollectionError`; 403/429 raise `SourceBlockedError`/`SourceRateLimitedError`.
---
### Glassdoor (`app/jobs/sources/glassdoor.py`)
* Uses **Playwright** to render the page because Glassdoor heavily relies on client‑side JavaScript.
* **Discovery** – Executes a GraphQL query to fetch a batch of job IDs; respects `max_jobs`.
* **Detail Fetch** – Navigates to each job page, extracts structured data via DOM selectors.
* **Fields** – Same as Dice, plus `experience_text` when available.
* **Rate Limiting** – Detects Cloudflare blocks; raises `SourceBlockedError`.
---
### LinkedIn (`app/jobs/sources/linkedin.py`)
* Pure HTTP client (`httpx`) – no browser needed.
* **Discovery** – Calls LinkedIn’s *seeMoreJobPostings* endpoint with pagination.
* **Detail Fetch** – Calls *jobPosting* endpoint for each ID, parses HTML with regex.
* **Extracted Fields** – Title, company, location, description, employment type, remote flag, skills, posted_at.
* **Deduplication** – Internal set of external IDs to avoid duplicates across pages.
---
### HiringCafe (`app/jobs/sources/hiringcafe.py`)
* Browser‑based scraper using **Playwright** (required to bypass Cloudflare Turnstile and Next.js streaming).
* **Discovery** – Builds a URL `https://hiringcafe.com/search?q=<query>&l=<location>` and loads the page.
* **NEXT_DATA Extraction** – Reads the `__NEXT_DATA__` script tag, parses JSON to obtain `ssrHits` – an array of job “hits”.
* **Detail Extraction** – All needed data (title, company, location, description, employment type, skills, posted_at) is already present inside each hit; no second network round‑trip.
* **Fields**
  * `title` – from `job_information.title` or `v5_processed_job_data.core_job_title`.
  * `company` – `v5_processed_job_data.company_name`.
  * `location` – `v5_processed_job_data.formatted_workplace_location`.
  * `url` – `apply_url` or fallback URL built from the job ID.
  * `employment_type` – first element of `commitment` array if present.
  * `skills` – tuple from `technical_tools`.
  * `description` – built from `requirements_summary` and `role_activities`.
  * `posted_at` – derived from `estimated_publish_date_millis` (epoch ms).
* **Error Handling** – Detects HTTP 403 or Cloudflare challenge text and raises `SourceBlockedError`; other exceptions are logged and cause the collector to return an empty list.
---
## Error Types (`app/jobs/errors.py`)
| Exception | Meaning |
|-----------|---------|
| `SourceBlockedError` | Permanent block (e.g., Cloudflare challenge, 403). The coordinator logs and skips the source for the current run.
| `SourceRateLimitedError` | HTTP 429 – the collector should back‑off; the exception carries `retry_after_seconds`.
| `TemporaryCollectionError` | Network time‑outs, DNS failures, transient HTTP errors – safe to retry on the next schedule.
| `SourceUnavailableError` | No collector registered for the requested source (raised by registry).
---
## Adding a New Scraper
1. **Create a module** under `app/jobs/sources/` named `<source>.py`.
2. **Implement the collector class**:
   ```python
   from app.jobs.errors import SourceBlockedError, TemporaryCollectionError
   from app.jobs.normalization import RawSourceJob
   from app.jobs.targets import CollectionTarget
   from app.domain.jobs import JobSource


   class MySourceCollector:
       source = JobSource.MY_SOURCE

       async def discover(self, target: CollectionTarget) -> Sequence[DiscoveredSourceJob]:
           # return lightweight candidates respecting target.max_jobs
           ...

       async def fetch_details(
           self, target: CollectionTarget, candidates: Sequence[DiscoveredSourceJob]
       ) -> Sequence[RawSourceJob]:
           # return fully populated RawSourceJob objects
           ...
   ```
3. **Add the collector to the registry** in `app/jobs/registry.py` inside `build_collector_registry()`.
4. **Update the `JobSource` enum** (`app/domain/jobs.py`) with the new source value.
5. **Write unit tests** in `tests/unit/` using the `CollectorRegistry` to resolve the collector and exercise both methods.
6. **Run lint and type‑check** – the collector must be fully typed and async‑compatible.
---
## Testing Scrapers
* **Unit tests** – mock HTTP responses (`httpx.AsyncClient`) or Playwright page objects using `unittest.mock`. Verify that the returned `RawSourceJob` contains the expected fields.
* **Integration test** – run `scripts/collect_jobs.py` with `--source <new>` against a real environment (prefer a staging environment with a throttling‑friendly proxy).
* **CI** – all collector tests are part of the `pytest` suite and must pass without network access; use fixture recordings where possible.
---
*All documentation reflects the current implementation; no code changes are made by this file.*
