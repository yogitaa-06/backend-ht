# Troubleshooting Documentation

This guide helps you diagnose and resolve the most common problems encountered while developing or operating the **HireAndTech** backend.

---
## 1. Application Startup Issues
| Symptom | Possible Cause | Investigation Steps | Fix |
|---|---|---|---|
| `ImportError` / missing module | Dependency not installed or virtualenv not activated | Run `uv sync` and ensure the correct Python version (`python --version`) | Re‑install dependencies with `uv sync` |
| `DatabaseError: could not connect to server` | `DATABASE_URL` wrong, Postgres not running, network firewall | Verify `psql` connection using the same URL, check container logs | Update `.env` with correct credentials, start Postgres, expose port |
| Alembic migration failure | Schema drift, missing migration script | Run `uv run alembic current` and compare with `uv run alembic heads` | Create a new migration (`uv run alembic revision --autogenerate -m "..."`) and apply (`uv run alembic upgrade head`) |

---
## 2. Collector / Scraper Problems
| Symptom | Source | Debug Steps | Resolution |
|---|---|---|---|
| No jobs returned from a source (e.g., HiringCafe) | Collector `discover()` returns empty list | 1. Enable debug logging (`LOG_LEVEL=DEBUG`). 2. Check Playwright logs in `/tmp/playwright` (or the `artifacts` folder). 3. Verify the target URL is reachable from the container. | Update selector / JSON path in the collector, or adjust page wait conditions. |
| `max_jobs` flag ignored (more jobs processed) | `CollectionCoordinator` not respecting `max_jobs` during `fetch_details()` loop | 1. Insert a breakpoint or `logger.debug` after each job is persisted. 2. Confirm the `max_jobs` value propagates from CLI (`scripts/collect_jobs.py`) to `CollectionTarget`. | Fix the loop to break after `processed >= target.max_jobs`. |
| Scraper crashes with `TimeoutError` | Playwright timeout too low, site loading slowly, Cloudflare challenge | Run the collector manually (`uv run python -m app.jobs.collectors.hiringcafe`) with `headless=False` to see the browser. | Increase `page.set_default_timeout`, add retry logic, or solve Cloudflare challenge. |
| Extracted fields are `null` (title, company, location) | Normalizer mapping missing keys from raw payload | Inspect raw JSON saved in `job_sources` table (`SELECT raw_data FROM job_sources WHERE source='hiringcafe' LIMIT 1`). | Extend `HiringCafeNormalizer` to map the missing fields; ensure field names match the source JSON. |

---
## 3. IP Allow‑list & Rate Limiting
| Symptom | Likely Trigger | How to Verify |
|---|---|---|
| `403 Forbidden` on every request | `ip_allowlist_enabled` true but no matching rule | Look at audit logs (`SELECT * FROM security_audit_events WHERE event_type='IP_ACCESS_DENIED'`). | Add a CIDR rule via the admin API or disable the allow‑list (`IP_ALLOWLIST_ENABLED=false`). |
| `429 Too Many Requests` after a few calls | Rate limit exceeded for the client IP | Check middleware logs (`rate_limit_store_failure` or `RATE_LIMITED`). | Increase limit in `Settings` or configure a shared Redis store for higher capacity. |

---
## 4. Deployment / Container Problems
| Issue | Check |
|---|---|
| Container exits with code 1 | `docker logs <container>` for stack trace. |
| Health probe fails (`/health` returns 5xx) | Inside container: `curl http://localhost:8000/health`. Verify DB connectivity and migrations. |
| Missing environment variables | `docker exec -it <container> env | grep JWT` – ensure all required vars are present. |

---
## 5. General Tips
* **Run tests frequently** – `uv run pytest` catches regressions before they reach production.
* **Check CI artifacts** – lint (`ruff`), type (`mypy`), and secret‑scan results are posted on pull‑request checks.
* **Use the audit view** – `GET /admin/security/audit` provides a searchable list of security events.
* **Enable back‑trace** – set `PYTHONFAULTHANDLER=1` in the environment to get native stack traces on crashes.

---
*All guidance reflects the current repository state; no code modifications are made by this document.*
