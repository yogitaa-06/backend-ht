# Implementation Plan: Worker Isolation & AI Enrichment

This document details the technical implementation steps for separating the asynchronous worker pools (Phase 1) and implementing the persistent job matching and AI enrichment pipeline (Phase 2).

## Phase 1: Worker Isolation & Queue Configuration 🚦

**Goal:** Ensure that different background workloads (scraping, searching, and AI processing) operate on independent queues and worker pools. This guarantees that if one component (e.g., scraping) is delayed, it will not block user searches or AI enrichment.

### 1. Update Core Configuration
**File:** `app/core/config.py`
- Extend the `Settings` class to define explicit Redis queue names for each domain.
- **Additions:**
  ```python
  scrape_queue_name: str = Field(default="hireandtech:scrape", min_length=1)
  search_queue_name: str = Field(default="hireandtech:search", min_length=1)
  ai_queue_name: str = Field(default="hireandtech:ai", min_length=1)
  ```

### 2. Refactor Worker Configurations
**Directory:** `app/queue/workers/`
- Break down the monolithic `app/queue/worker.py` into dedicated, independently runnable modules.
- **Files to create:**
  - `app/queue/workers/scrape.py`: Contains `ScrapeWorkerSettings` (listens to `scrape_queue_name`).
  - `app/queue/workers/search.py`: Contains `SearchWorkerSettings` (listens to `search_queue_name`).
  - `app/queue/workers/ai.py`: Contains `AIWorkerSettings` (listens to `ai_queue_name`).
- *Note:* The existing `startup` and `shutdown` logic (e.g., DB connections) can be shared via a common base or imported utility, but each worker class must define its specific `functions` and `queue_name`.

### 3. Migrate Existing Collection Tasks
**Files:** `app/queue/tasks.py` & `app/queue/scheduler.py`
- Ensure `run_job_collection` and `schedule_due_collections` are exclusively registered in `ScrapeWorkerSettings` (`app/queue/workers/scrape.py`).
- Update the enqueue calls in the API and scheduler to target `settings.scrape_queue_name`.

### 4. Docker Compose Updates
**File:** `docker-compose.yml` (or equivalent infra files)
- Add separate service definitions for each worker pool to allow independent horizontal scaling.
- **Example Services:**
  - `worker-scrape`: `uv run arq app.queue.workers.scrape.ScrapeWorkerSettings`
  - `worker-search`: `uv run arq app.queue.workers.search.SearchWorkerSettings`
  - `worker-ai`: `uv run arq app.queue.workers.ai.AIWorkerSettings`

### 5. Health Check Monitoring
**File:** `app/api/v1/routes/health.py` (or `app/queue/health.py`)
- Enhance the health check endpoint to inspect the queue depth for all three Redis queues (`scrape`, `search`, and `ai`).

---

## Phase 2: Persistent `job_matches` & AI Enrichment 🧠

**Goal:** Decouple match computation from API read latency and integrate AI-driven resume analysis without blocking the initial search results.

### 1. Database Schema & Migrations
**Files:** `app/domain/jobs.py` & `alembic/versions/`
- Create the `JobMatch` SQLAlchemy model. This acts as a join table between `Profile` and `CanonicalJob`.
- **Fields:**
  - `profile_id` (UUID)
  - `job_id` (UUID)
  - `match_score`, `skills_score`, `experience_score` (Float)
  - AI Enrichment Fields: `ai_strengths`, `ai_concerns`, `ai_tips` (String/Text)
- Generate the Alembic migration: `uv run alembic revision --autogenerate -m "add_job_matches_table"`

### 2. Repository Layer
**File:** `app/repositories/job_matches.py`
- Create `JobMatchRepository` to handle saving and retrieving user-specific job matches.
- Must include methods for batch upserting to handle thousands of filtered matches efficiently.

### 3. The Search Matching Worker Task
**File:** `app/queue/search_tasks.py`
- Create the `run_search_job(ctx, search_id: UUID)` ARQ task.
- **Workflow:**
  1. Load the user's `CandidateProfile`.
  2. Query the `CanonicalJob` global database and apply deterministic filters (location, title, remote_type).
  3. Calculate base matching scores (e.g., overlapping skills, experience bounds).
  4. Persist the scored results into the `job_matches` table using `JobMatchRepository`.
  5. Enqueue the top *N* matches to the AI worker queue (`ai_queue_name`).

### 4. The AI Enrichment Worker Task
**File:** `app/queue/ai_tasks.py`
- Create the `evaluate_matches(ctx, profile_id: UUID, job_ids: list[UUID])` ARQ task.
- **Workflow:**
  1. Load the candidate's resume/profile details and the descriptions of the provided `job_ids`.
  2. Call the LLM integration (e.g., OpenAI) with a structured prompt to evaluate the fit.
  3. Parse the LLM response.
  4. Update the respective `JobMatch` records with `ai_strengths`, `ai_concerns`, and `ai_tips`.

### 5. Update API Endpoints
**File:** `app/api/v1/routes/jobs.py`
- Modify `GET /api/v1/jobs/recommended` (or the equivalent search results endpoint) to read directly from the persistent `job_matches` table.
- Results will initially return base scores, and as the AI worker finishes processing in the background, subsequent reads will automatically contain the populated AI enrichment fields.
