# Development Documentation

This guide covers everything you need to start developing on the **HireAndTech** backend.

## Prerequisites
* **Python 3.11+** (managed with `uv`).
* **PostgreSQL** (local dev instance, default port 5432).
* **Node** & **npm** for the frontend (already running separately).
* **Playwright** browsers – install with `uv run playwright install` (used by the HiringCafe scraper).

## Repository Setup
```bash
# Clone the repo (already done)
cd "C:/Users/hntadmin/Desktop/Hire and Tech/backend-ht"

# Install dependencies via uv (the project ships a uv.lock)
uv sync

# Copy the example environment file and fill in secrets
cp .env.example .env
# Edit .env – set DATABASE_URL, JWT_SECRET_KEY, etc.
```

## Database
```bash
# Create a local database
echo "CREATE DATABASE hireandtech;" | psql -U postgres

# Run migrations (Alembic)
uv run alembic upgrade head
```

## Running the Service
```bash
uv run uvicorn app.main:app --reload
```
*The server will be reachable at `http://127.0.0.1:8000`.*

## Testing
```bash
# Unit tests
uv run pytest -q

# Coverage (target 90 %)
uv run coverage run -m pytest && uv run coverage report
```
Tests are located under `tests/`.  They use `pytest‑asyncio` for async code and `respx`/`playwright` fixtures to mock external HTTP calls.

## Code Quality
* **Ruff** – `uv run ruff check .` and `uv run ruff format .`
* **Mypy** – `uv run mypy app`
* Pre‑commit hooks are configured (`.pre-commit-config.yaml`).  Run `uv run pre-commit install` to enable them locally.

## IDE Integration
* The project ships a **pyright** configuration (`pyrightconfig.json`).  Import the workspace into VS Code and enable the *Python* extension for IntelliSense.
* Use the **Run > Debug** configuration `Backend` (launches `uvicorn` with the debugger attached).

## Adding a New Scraper
1. Create a new module under `app/jobs/sources/` implementing the `Collector` protocol.
2. Register it in `app/jobs/registry.py` via `build_collector_registry()`.
3. Add unit tests in `tests/unit/` covering discovery and normalization.
4. Update `docs/scrapers.md` with the new source description.

---
*All statements reflect the current repository implementation; no code changes are performed by this document.*
