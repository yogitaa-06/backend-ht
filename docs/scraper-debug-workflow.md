# Scraper Debug Workflow

**Purpose**: Show, in very simple English, how a job scraper (for example the HiringCafe collector) runs from start to finish.  This guide is meant for people who are new to the code base and need to understand where to look when something goes wrong.

---
## 1. Entry point – `scripts/collect_jobs.py`
1. The command line tool calls **`collect_jobs.py`** with arguments like `--source hiringcafe --query "Software Engineer" --location "United States" --max-jobs 2`.
2. The script creates a **`CollectionTarget`** object that stores the source name, query, location and the `max_jobs` limit.
3. It builds a **`CollectionCoordinator`** (see `app/jobs/collection.py`).
4. The coordinator picks the correct **collector class** from the registry (`app/jobs/registry.py`). For HiringCafe it gets `HiringCafeCollector`.
5. The coordinator calls `collector.collect(target)`.

---
## 2. Collector – `app/jobs/sources/hiringcafe.py`
1. **Playwright** is started (`async_playwright`). This opens a head‑less Chromium browser.
2. The collector builds the search URL using the query and optional location.
3. `page.goto(search_url)` loads the page.  It waits for the DOM to be ready (`domcontentloaded`).
4. The code checks the HTTP status – if it is `403` a `SourceBlockedError` is raised.
5. A short pause (`wait_for_timeout(3000)`) gives the page time to render the job list.
6. The page text is examined for the phrase *"Performance and Security by Cloudflare"* – if found, a `SourceBlockedError` is raised (Cloudflare challenge).
7. The scraper extracts the JSON blob inside the element `__NEXT_DATA__` – this contains the server‑side rendered job data.
8. The JSON is parsed and the list `ssr_hits` is read.  Each **hit** represents one job.
9. For each hit (up to `max_jobs`):
   * Pull fields: title, company, location, URL, employment type, skills, description, posted date, etc.
   * Build a **`RawSourceJob`** instance – this is a plain data object defined in `app/jobs/normalization.py`.
   * Append the `RawSourceJob` to the list `yielded_jobs`.
10. After the loop the browser is closed and the list of `RawSourceJob`s is returned to the coordinator.

---
## 3. Normalization – `app/jobs/normalization.py`
1. The coordinator receives the list of `RawSourceJob`s.
2. For each raw job it calls `normalize_job(raw_job)`.
3. Normalization creates a **`NormalizedJob`** (still a Python dataclass) that:
   * Normalizes the title (e.g., removes extra whitespace, lower‑cases for canonical mapping).
   * Derives a **role family** (e.g., "software_engineer") using a simple heuristic.
   * Converts the posted date to UTC `datetime` if present.
   * Keeps the list of skills as‑is.
4. The normalized job is passed to the **canonical ingestion service** (`app/jobs/ingestion.py`).

---
## 4. Canonical Ingestion – `app/jobs/ingestion.py`
1. The service checks if a **canonical job** already exists for the same source and external ID.
2. If it does not exist, a new `CanonicalJob` row is created in the `jobs` table.
3. A **`JobSourceObservation`** row is created linking the source listing to the canonical job.  It stores the raw JSON (`raw_data`) and a SHA‑256 `content_hash` for deduplication.
4. The service also updates the legacy `global_jobs` table for backward compatibility.
5. All changes are committed in a single database transaction.

---
## 5. API exposure – `app/api` (GET `/jobs`)
1. The API endpoint reads from the **canonical jobs** view (`CanonicalJob` model).
2. It joins the related `Company` and `JobSourceObservation` records to build the **API schema** (`JobRead`).
3. The frontend receives fields such as `title`, `company`, `location`, `employment_type`, `skills`, `description`, `source`, and `posted_at`.

---
## 6. Where to Look When Things Go Wrong
| Problem | Likely Place | How to Inspect |
|---|---|---|
| No jobs returned | Collector (`HiringCafeCollector.collect`) did not find `__NEXT_DATA__` or `ssr_hits` is empty. | Add `logger.debug` after line 66 to print the JSON size. Run the collector manually with `headless=False` to see the page. |
| Fields are `null` (title, company, location) | Normalization may drop values if they are missing in the raw job. | Check `RawSourceJob` values in the debugger right after line 138 in the collector. |
| `max_jobs` ignored | The coordinator does not stop after the limit. | Verify the `max_jobs` variable is passed correctly (line 74‑76) and that the loop condition (`len(yielded_jobs) >= max_jobs`) is evaluated. |
| Rate‑limit / IP block | Middleware (`IpSecurityMiddleware`). | Look at audit logs in the `security_audit_events` table (`SELECT * FROM security_audit_events WHERE event_type='IP_ACCESS_DENIED'`). |
| Database error on insert | Ingestion (`CanonicalJobIngestionService`). | Enable SQL echo (`SQLALCHEMY_ECHO=True`) to see the failing INSERT statement. |

---
## 7. Quick Debug Checklist
1. Run the collector directly:
   ```bash
   uv run python -m app.jobs.sources.hiringcafe collect --query "Software Engineer" --location "United States" --max-jobs 2
   ```
2. Verify the returned `RawSourceJob` objects contain the expected fields.
3. Run the normalization step in a Python REPL:
   ```python
   from app.jobs.normalization import normalize_job
   norm = normalize_job(raw_job)
   print(norm)
   ```
4. Check the database row after ingestion:
   ```sql
   SELECT * FROM job_sources WHERE source='hiringcafe' ORDER BY created_at DESC LIMIT 5;
   ```
5. Query the API endpoint and confirm the JSON contains the fields.

---
*All statements reflect the current repository implementation; no code changes are performed by this document.*
