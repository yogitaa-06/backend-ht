# 🏗️ HireAndTech — Professional Rebuild Plan

> **Objective**: Rebuild the entire HireAndTech platform (backend + frontend) from scratch so it reads, runs, and scales like a product built by a staff-level engineering team at a top-tier company.

---

## Table of Contents

1. [What We Have Today](#1-what-we-have-today)
2. [What Needs to Change](#2-what-needs-to-change)
3. [Technology Decisions](#3-technology-decisions)
4. [Monorepo vs Polyrepo](#4-monorepo-vs-polyrepo)
5. [Backend — Complete Blueprint](#5-backend--complete-blueprint)
6. [Frontend — Complete Blueprint](#6-frontend--complete-blueprint)
7. [Documentation Standards](#7-documentation-standards)
8. [CI/CD Pipeline](#8-cicd-pipeline)
9. [Docker and Infrastructure](#9-docker-and-infrastructure)
10. [Testing Strategy](#10-testing-strategy)
11. [Code Quality Standards](#11-code-quality-standards)
12. [Sprint-by-Sprint Execution Plan](#12-sprint-by-sprint-execution-plan)
13. [Migration Strategy](#13-migration-strategy)

---

## 1. What We Have Today

### Backend (`backend-ht`)
- **Stack**: Python 3.12, FastAPI, SQLAlchemy Async, ARQ, Redis, PostgreSQL
- **Lines of app code**: ~40 files across `app/`
- **Test files**: 45 unit tests, coverage target 90%
- **CI**: GitHub Actions with Ruff + Mypy + Pytest
- **Docker**: Single-stage Dockerfile
- **Docs**: 17 markdown files in `docs/`

**Problems**:
- `main.tsx` is 1,910 lines — the entire frontend is basically one file
- Frontend uses Vite + React 19 with hash-based routing (no proper router)
- Backend `architecture.md` has duplicate/contradicting sections (written at different times)
- No Docker Compose for local development
- No API versioning strategy beyond `/api/v1`
- No OpenAPI client generation for frontend
- Single ARQ worker pool for all task types
- No seed data, no dev fixtures
- No contribution guidelines, no changelog

### Frontend (`frontend-ht`)
- **Stack**: Vite + React 19 + TypeScript + Supabase Auth
- **Components**: Nearly everything is in `main.tsx` (~60KB)
- **Styling**: Single `styles.css` (39KB)
- **Pages**: Only `FreshJobs.tsx` is extracted; everything else is inlined
- **No router**: Hash-based navigation with `location.hash`
- **No state management**: Everything is local `useState`
- **No API client**: Manual `fetch` calls scattered everywhere

---

## 2. What Needs to Change

### The Professional Standard We Are Targeting

| Area | Current | Target |
|:---|:---|:---|
| **Project structure** | Flat, organic growth | Domain-driven, consistent naming |
| **Code comments** | Sparse, inconsistent | Every module has a docstring explaining why it exists |
| **README** | Functional but basic | Onboarding-ready: badges, quick start, architecture diagram |
| **API docs** | Auto-generated OpenAPI only | OpenAPI + hand-written guides + Postman collection |
| **Error handling** | Mixed approaches | Centralized error hierarchy + problem detail responses |
| **Logging** | Structured but ad-hoc | Correlation IDs, structured JSON, log levels per module |
| **Testing** | Good coverage, basic fixtures | Factories, fixtures, integration tests, contract tests |
| **Frontend** | Monolithic single file | Component library, proper routing, state management |
| **Docker** | Single Dockerfile | Docker Compose with all services, hot-reload dev mode |
| **CI/CD** | Basic lint + test | Multi-stage: lint, test, build, security scan, deploy |
| **Git** | Functional | Conventional commits, PR templates, branch protection |

---

## 3. Technology Decisions

### Backend (Keeping + Upgrading)

| Component | Choice | Why |
|:---|:---|:---|
| **Language** | Python 3.12+ | Already proven in current codebase, excellent async ecosystem |
| **Framework** | FastAPI | Best-in-class for async Python APIs, auto OpenAPI docs |
| **ORM** | SQLAlchemy 2.0 Async | Already working, mature async support |
| **Database** | PostgreSQL 16+ | Already deployed, battle-tested |
| **Queue** | ARQ (Redis-backed) | Lightweight, Python-native, already integrated |
| **Package Manager** | uv | Already using, fastest Python package manager |
| **Linting** | Ruff | Already using, replaces flake8/isort/black |
| **Type Checking** | Mypy (strict mode) | Already configured |
| **Testing** | Pytest + pytest-cov | Already working |
| **Migrations** | Alembic | Already configured |
| **Auth** | Supabase JWT | Already integrated |

### Frontend (Major Upgrade)

| Component | Choice | Why |
|:---|:---|:---|
| **Framework** | Next.js 15 (App Router) | SSR, file-based routing, API routes, production-grade |
| **Language** | TypeScript (strict) | Already using TS, strict mode for safety |
| **Styling** | Tailwind CSS v4 + shadcn/ui | Professional component library, consistent design system |
| **State** | Zustand | Lightweight, TypeScript-first, no boilerplate |
| **API Client** | Generated from OpenAPI spec | Type-safe, auto-updated, zero drift |
| **Auth** | Supabase Auth + Next.js middleware | SSR-compatible auth with route protection |
| **Forms** | React Hook Form + Zod | Validation, performance, TypeScript integration |
| **Icons** | Lucide React | Already using |

### Infrastructure

| Component | Choice | Why |
|:---|:---|:---|
| **Container** | Docker + Docker Compose | Consistent local dev + prod parity |
| **CI/CD** | GitHub Actions | Already using, free for open source |
| **Monitoring** | Structured JSON logs + Sentry (future) | Start with logs, add APM later |

---

## 4. Monorepo vs Polyrepo

### Decision: Monorepo with separate packages

```
hireandtech/
├── apps/
│   ├── api/              ← FastAPI backend (Python)
│   └── web/              ← Next.js frontend (TypeScript)
├── packages/
│   └── openapi/          ← Generated API client (shared types)
├── infra/
│   ├── docker/           ← Dockerfiles per service
│   └── compose/          ← Docker Compose configs
├── docs/                 ← Project-wide documentation
├── scripts/              ← Dev utilities
├── .github/              ← CI/CD workflows
├── README.md             ← Root README
├── CONTRIBUTING.md       ← Contribution guidelines
├── CHANGELOG.md          ← Versioned changelog
├── LICENSE               ← MIT or proprietary
└── Makefile              ← One-command dev workflows
```

**Why monorepo**:
- One PR can change backend API + frontend consumer + docs atomically
- Shared CI — a backend API change triggers frontend type-check
- OpenAPI client auto-generates when backend schemas change
- Simpler onboarding — `git clone` + `make dev` and everything runs

---

## 5. Backend — Complete Blueprint

### 5.1 Directory Structure

```
apps/api/
├── app/
│   ├── __init__.py                 # Package version (__version__)
│   ├── main.py                     # FastAPI app factory — no business logic
│   │
│   ├── core/                       # Cross-cutting infrastructure
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings (all env vars)
│   │   ├── logging.py              # Structured JSON logging setup
│   │   ├── errors.py               # Global exception handlers + Problem Detail
│   │   ├── middleware.py            # Request ID, timing, correlation
│   │   └── events.py               # Startup/shutdown lifecycle hooks
│   │
│   ├── auth/                       # Authentication boundary
│   │   ├── __init__.py
│   │   ├── verifier.py             # Supabase JWT verification
│   │   ├── dependencies.py         # FastAPI Depends() for current user
│   │   └── models.py               # Auth-specific data models
│   │
│   ├── domain/                     # Domain models (SQLAlchemy ORM)
│   │   ├── __init__.py
│   │   ├── base.py                 # Base model, mixins (ID, timestamps)
│   │   ├── jobs.py                 # CanonicalJob, Company, JobSourceObservation
│   │   ├── matches.py              # JobMatch (NEW — user-specific scores)
│   │   ├── profiles.py             # Profile
│   │   ├── resumes.py              # Resume, CandidateProfile
│   │   ├── applications.py         # Application tracking (NEW)
│   │   └── security.py             # IP rules, audit events
│   │
│   ├── repositories/               # Database access layer (SQL queries)
│   │   ├── __init__.py
│   │   ├── jobs.py                 # Canonical job CRUD
│   │   ├── matches.py              # Job match persistence (NEW)
│   │   ├── companies.py            # Company resolution
│   │   ├── resumes.py              # Resume + candidate profile queries
│   │   ├── applications.py         # Application CRUD (NEW)
│   │   └── profiles.py             # User profile queries
│   │
│   ├── services/                   # Business logic orchestration
│   │   ├── __init__.py
│   │   ├── job_search.py           # Search + filter + rank
│   │   ├── job_matching.py         # Deterministic scoring engine
│   │   ├── job_ingestion.py        # Normalize, dedupe, persist
│   │   ├── resume_parser.py        # PDF extraction + field parsing
│   │   └── resume_service.py       # Resume upload/delete orchestration
│   │
│   ├── collection/                 # Job collection engine
│   │   ├── __init__.py
│   │   ├── coordinator.py          # Scrape, normalize, persist pipeline
│   │   ├── normalization.py        # RawJob to NormalizedJob
│   │   ├── canonicalization.py     # SHA-256 dedup hashing
│   │   ├── errors.py               # Collection error hierarchy
│   │   ├── locks.py                # Redis distributed locks
│   │   ├── circuit_breaker.py      # Source circuit breaker (NEW)
│   │   ├── registry.py             # Source to Collector factory
│   │   ├── targets.py              # CollectionTarget definition
│   │   └── sources/                # One module per job board
│   │       ├── __init__.py
│   │       ├── base.py             # Abstract collector protocol
│   │       ├── dice.py
│   │       ├── glassdoor.py
│   │       ├── linkedin.py
│   │       └── hiringcafe.py
│   │
│   ├── queue/                      # Background task infrastructure
│   │   ├── __init__.py
│   │   ├── client.py               # Redis connection factory
│   │   ├── health.py               # Queue health monitoring
│   │   ├── scheduler.py            # Cron-based collection scheduler
│   │   ├── tasks/                  # Task handlers (one file per domain)
│   │   │   ├── __init__.py
│   │   │   ├── collection.py       # run_job_collection
│   │   │   ├── search.py           # run_async_search (NEW)
│   │   │   └── ai_enrichment.py    # evaluate_matches (NEW)
│   │   └── workers/                # Independent worker entry points
│   │       ├── __init__.py
│   │       ├── scrape.py           # ScrapeWorkerSettings
│   │       ├── search.py           # SearchWorkerSettings (NEW)
│   │       └── ai.py               # AIWorkerSettings (NEW)
│   │
│   ├── api/                        # HTTP layer — routes only
│   │   ├── __init__.py
│   │   ├── deps.py                 # Shared FastAPI dependencies
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py           # v1 router aggregation
│   │       └── routes/
│   │           ├── __init__.py
│   │           ├── jobs.py          # GET /jobs, GET /jobs/recommended
│   │           ├── search.py        # POST /search, GET /search/:id (NEW)
│   │           ├── resumes.py       # POST/GET /resumes
│   │           ├── applications.py  # POST/GET /applications (NEW)
│   │           ├── health.py        # GET /health
│   │           ├── auth.py          # POST /auth/...
│   │           └── admin.py         # Admin endpoints
│   │
│   ├── schemas/                    # Pydantic request/response models
│   │   ├── __init__.py
│   │   ├── jobs.py
│   │   ├── search.py               # SearchRequest, SearchProgress (NEW)
│   │   ├── resumes.py
│   │   ├── applications.py         # (NEW)
│   │   └── common.py               # Pagination, error responses
│   │
│   ├── security/                   # Security middleware
│   │   ├── __init__.py
│   │   ├── rate_limit.py           # Rate limiter (memory + Redis)
│   │   ├── middleware.py           # IP allowlist, request security
│   │   └── ip.py                   # Trusted proxy resolution
│   │
│   └── db/                         # Database infrastructure
│       ├── __init__.py
│       ├── session.py              # Async session factory
│       ├── base.py                 # Declarative base + mixins
│       └── urls.py                 # Connection URL parsing
│
├── migrations/                     # Alembic migrations
│   ├── env.py
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_canonical_jobs.py
│       ├── 003_job_matches.py      # NEW
│       └── 004_applications.py     # NEW
│
├── tests/
│   ├── conftest.py                 # Shared fixtures, factories
│   ├── factories/                  # Test data factories
│   │   ├── __init__.py
│   │   ├── jobs.py                 # JobFactory, CompanyFactory
│   │   ├── resumes.py              # ResumeFactory, CandidateFactory
│   │   └── profiles.py             # ProfileFactory
│   ├── unit/                       # Pure logic tests (no DB, no network)
│   │   ├── test_matching.py
│   │   ├── test_normalization.py
│   │   ├── test_canonicalization.py
│   │   ├── test_circuit_breaker.py
│   │   └── ...
│   ├── integration/                # Database + service tests
│   │   ├── test_job_ingestion.py
│   │   ├── test_job_search.py
│   │   └── ...
│   └── api/                        # HTTP endpoint tests
│       ├── test_jobs_api.py
│       ├── test_search_api.py
│       └── ...
│
├── scripts/
│   ├── collect_jobs.py             # CLI for manual job collection
│   ├── seed_dev_data.py            # Generate dev fixtures (NEW)
│   └── generate_openapi.py         # Export OpenAPI JSON (NEW)
│
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── alembic.ini
├── .env.example
└── README.md
```

### 5.2 Code Style Rules

Every Python file must follow these rules:

```python
"""
Module-level docstring explaining WHY this module exists.

Not what it does (the code shows that), but why it exists
as a separate module and what role it plays in the architecture.
"""

from __future__ import annotations

# Standard library imports
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# Third-party imports
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from app.core.config import Settings
from app.db.session import get_session

logger = logging.getLogger(__name__)


class ServiceName:
    """One-line description of what this class does.

    Extended explanation of the design decision, why this class
    exists, and how it fits into the larger architecture.

    Example:
        >>> service = ServiceName(repository)
        >>> result = await service.do_thing(session, param="value")
    """

    def __init__(self, repository: RepositoryType) -> None:
        """Initialize with required dependencies (dependency injection)."""
        self._repository = repository

    async def do_thing(
        self,
        session: AsyncSession,
        *,
        param: str,
        limit: int = 50,
    ) -> Result:
        """Verb phrase describing the action.

        Args:
            session: Database session for this unit of work.
            param: What this parameter controls.
            limit: Maximum number of results. Defaults to 50.

        Returns:
            Description of what is returned and its structure.

        Raises:
            NotFoundError: When the requested entity does not exist.
            ValidationError: When input constraints are violated.
        """
        ...
```

### 5.3 Docstring Convention

| Element | Rule |
|:---|:---|
| **Every module** | Module docstring explaining why it exists |
| **Every class** | One-liner + extended explanation + example usage |
| **Every public method** | Verb phrase + Args + Returns + Raises |
| **Private methods** | One-liner only (implementation detail) |
| **Constants** | Inline comment explaining the value choice |
| **Type aliases** | Comment explaining what the type represents |

### 5.4 Error Response Format (RFC 9457 Problem Detail)

```json
{
    "type": "https://api.hireandtech.com/errors/not-found",
    "title": "Resource Not Found",
    "status": 404,
    "detail": "Job with ID 'abc-123' does not exist.",
    "instance": "/api/v1/jobs/abc-123",
    "trace_id": "req_7f3a2b1c"
}
```

---

## 6. Frontend — Complete Blueprint

### 6.1 Directory Structure (Next.js 15 App Router)

```
apps/web/
├── src/
│   ├── app/                          # Next.js App Router
│   │   ├── layout.tsx                # Root layout (fonts, theme, providers)
│   │   ├── page.tsx                  # Landing page
│   │   ├── globals.css               # Tailwind imports + CSS variables
│   │   ├── loading.tsx               # Global loading skeleton
│   │   ├── error.tsx                 # Global error boundary
│   │   ├── not-found.tsx             # 404 page
│   │   │
│   │   ├── (auth)/                   # Auth group (no sidebar)
│   │   │   ├── login/page.tsx
│   │   │   ├── signup/page.tsx
│   │   │   └── layout.tsx
│   │   │
│   │   ├── (dashboard)/              # Dashboard group (with sidebar)
│   │   │   ├── layout.tsx            # Sidebar + header layout
│   │   │   ├── overview/page.tsx     # Dashboard overview
│   │   │   ├── jobs/
│   │   │   │   ├── page.tsx          # Job search page
│   │   │   │   └── [id]/page.tsx     # Job detail page
│   │   │   ├── recommended/
│   │   │   │   └── page.tsx          # AI-matched jobs
│   │   │   ├── resumes/
│   │   │   │   ├── page.tsx          # Resume list
│   │   │   │   └── upload/page.tsx   # Upload flow
│   │   │   ├── applications/
│   │   │   │   └── page.tsx          # Application tracker
│   │   │   ├── profile/
│   │   │   │   └── page.tsx          # Candidate profile
│   │   │   └── settings/
│   │   │       └── page.tsx          # Account settings
│   │   │
│   │   └── api/                      # Next.js API routes (BFF)
│   │       └── auth/
│   │           └── callback/route.ts # Supabase OAuth callback
│   │
│   ├── components/                   # Reusable UI components
│   │   ├── ui/                       # shadcn/ui primitives
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── input.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── skeleton.tsx
│   │   │   ├── toast.tsx
│   │   │   └── ...
│   │   ├── layout/                   # Layout components
│   │   │   ├── sidebar.tsx
│   │   │   ├── header.tsx
│   │   │   ├── mobile-nav.tsx
│   │   │   └── breadcrumbs.tsx
│   │   ├── jobs/                     # Job-domain components
│   │   │   ├── job-card.tsx
│   │   │   ├── job-list.tsx
│   │   │   ├── job-filters.tsx
│   │   │   ├── job-detail.tsx
│   │   │   ├── match-score-badge.tsx
│   │   │   └── salary-range.tsx
│   │   ├── resumes/                  # Resume-domain components
│   │   │   ├── resume-card.tsx
│   │   │   ├── resume-upload.tsx
│   │   │   ├── skills-chart.tsx
│   │   │   └── profile-summary.tsx
│   │   └── shared/                   # Cross-cutting components
│   │       ├── data-table.tsx
│   │       ├── empty-state.tsx
│   │       ├── error-boundary.tsx
│   │       ├── loading-spinner.tsx
│   │       └── pagination.tsx
│   │
│   ├── hooks/                        # Custom React hooks
│   │   ├── use-auth.ts               # Authentication state
│   │   ├── use-jobs.ts               # Job search + pagination
│   │   ├── use-recommendations.ts    # Recommended jobs
│   │   ├── use-resumes.ts            # Resume CRUD
│   │   ├── use-debounce.ts           # Input debouncing
│   │   └── use-media-query.ts        # Responsive breakpoints
│   │
│   ├── lib/                          # Utilities and clients
│   │   ├── api-client.ts             # Generated OpenAPI client wrapper
│   │   ├── supabase/
│   │   │   ├── client.ts             # Browser Supabase client
│   │   │   ├── server.ts             # Server-side Supabase client
│   │   │   └── middleware.ts         # Auth middleware
│   │   ├── utils.ts                  # General utilities (cn, formatDate)
│   │   └── constants.ts              # App-wide constants
│   │
│   ├── stores/                       # Zustand state stores
│   │   ├── auth-store.ts             # User session state
│   │   ├── job-store.ts              # Job search filters + results
│   │   └── ui-store.ts               # Theme, sidebar collapse, etc.
│   │
│   └── types/                        # TypeScript type definitions
│       ├── api.ts                    # Generated from OpenAPI
│       ├── auth.ts                   # Auth-specific types
│       └── index.ts                  # Re-exports
│
├── public/
│   ├── favicon.ico
│   ├── og-image.png                  # Social sharing image
│   └── robots.txt
│
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
├── .env.example
├── .env.local
└── README.md
```

### 6.2 Key Frontend Patterns

**Component structure** — every component file follows:

```tsx
/**
 * JobCard — Displays a single job listing in search results.
 *
 * Shows title, company, location, salary range, skill badges,
 * and match score when available. Supports compact and expanded layouts.
 */

"use client";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { Job } from "@/types/api";

interface JobCardProps {
  /** The canonical job data from the API. */
  job: Job;
  /** Optional match score (0-100) from recommendation engine. */
  matchScore?: number;
  /** Layout variant. Defaults to "default". */
  variant?: "default" | "compact";
  /** Callback when the user clicks the card. */
  onSelect?: (jobId: string) => void;
}

export function JobCard({
  job,
  matchScore,
  variant = "default",
  onSelect,
}: JobCardProps) {
  // ...component implementation
}
```

---

## 7. Documentation Standards

### 7.1 Required Documents

| Document | Location | Purpose |
|:---|:---|:---|
| **README.md** (root) | `/README.md` | First thing anyone sees — badges, quick start, architecture overview |
| **README.md** (api) | `/apps/api/README.md` | Backend-specific setup, env vars, running locally |
| **README.md** (web) | `/apps/web/README.md` | Frontend-specific setup, env vars, running locally |
| **CONTRIBUTING.md** | `/CONTRIBUTING.md` | How to contribute — branch naming, commit format, PR process |
| **CHANGELOG.md** | `/CHANGELOG.md` | Versioned changelog following Keep a Changelog format |
| **Architecture** | `/docs/architecture.md` | System design — the V4 document we already created |
| **API Guide** | `/docs/api-guide.md` | Hand-written endpoint guide with examples |
| **Database Schema** | `/docs/database.md` | ER diagrams, migration guide |
| **Deployment** | `/docs/deployment.md` | How to deploy to production |
| **Development** | `/docs/development.md` | Local dev setup, troubleshooting |
| **ADR Directory** | `/docs/adr/` | Architecture Decision Records — one file per major decision |

### 7.2 Root README Structure

The root README should include:
- Project title with tagline
- CI/Coverage/License badges
- Quick start guide (< 5 minutes with `make dev`)
- Architecture Mermaid diagram
- Project structure overview
- Documentation links table
- Tech stack summary
- License

### 7.3 Architecture Decision Records (ADR)

Each major design decision gets a numbered markdown file:

```
docs/adr/
├── 001-monorepo-structure.md
├── 002-background-collection-over-user-triggered.md
├── 003-canonical-job-deduplication.md
├── 004-deterministic-matching-before-ai.md
├── 005-independent-worker-pools.md
├── 006-async-search-ticket-pattern.md
└── 007-nextjs-app-router-over-vite-spa.md
```

Each ADR follows: **Status** > **Date** > **Context** > **Decision** > **Consequences**

---

## 8. CI/CD Pipeline

### 8.1 GitHub Actions Workflows

**Backend CI** (`backend.yml`):
1. **Lint job**: Ruff check + Ruff format + Mypy
2. **Test job**: Pytest with PostgreSQL + Redis services, Codecov upload
3. **Build job**: Docker build (depends on lint + test passing)
4. **Security job**: pip-audit (dependency vulnerabilities) + bandit (Python security)

**Frontend CI** (`frontend.yml`):
1. **Lint job**: ESLint + TypeScript type-check + Prettier
2. **Test job**: Jest/Vitest unit tests + Playwright E2E
3. **Build job**: Next.js production build (depends on lint + test passing)

Both workflows trigger on:
- Pull requests touching their respective `apps/` directory
- Push to `main` branch

### 8.2 Git Workflow

| Rule | Standard |
|:---|:---|
| **Branching** | `main` (production), `develop` (integration), `feature/xxx`, `fix/xxx` |
| **Commits** | Conventional Commits: `feat(jobs):`, `fix(auth):`, `docs:`, `chore:` |
| **PRs** | Require 1 review + CI passing + no merge conflicts |
| **Releases** | Semantic versioning via GitHub Releases |

---

## 9. Docker and Infrastructure

### 9.1 Docker Compose (Local Development)

Services in `infra/compose/docker-compose.dev.yml`:

| Service | Image/Build | Port | Purpose |
|:---|:---|:---:|:---|
| **postgres** | `postgres:16-alpine` | 5432 | Database with health check |
| **redis** | `redis:7-alpine` | 6379 | Queue broker with health check |
| **api** | Build from `apps/api` | 8000 | FastAPI with hot-reload volume mount |
| **scrape-worker** | Build from `apps/api` | — | ARQ scrape worker (independent process) |
| **search-worker** | Build from `apps/api` | — | ARQ search worker (independent process) |
| **web** | Build from `apps/web` | 3000 | Next.js with hot-reload volume mount |

All services depend on healthy postgres and redis before starting.

### 9.2 Makefile Commands

| Command | Action |
|:---|:---|
| `make dev` | Start all services, print URLs |
| `make stop` | Stop all services |
| `make test` | Run backend + frontend tests |
| `make lint` | Lint all code (Ruff + Mypy + ESLint) |
| `make format` | Auto-format all code |
| `make migrate` | Run Alembic migrations |
| `make seed` | Generate development fixtures |
| `make openapi` | Export OpenAPI schema + generate TS client |

---

## 10. Testing Strategy

### 10.1 Test Pyramid

```
         /\
        /  \       E2E Tests (Playwright)
       /----\      5-10 critical user flows
      /      \
     / API    \    API Integration Tests
    /  Tests   \   Every endpoint, auth, errors
   /------------\
  / Integration  \  Service + Repository Tests
 /   Tests        \ With real PostgreSQL
/------------------\
/    Unit Tests      \  Pure logic, no I/O
/--------------------\  Matching, normalization, hashing
```

### 10.2 Test Data Factories

Instead of copy-pasting test data, use factories that produce valid, minimal domain objects with sensible defaults. Override specific fields to test edge cases.

```python
class JobFactory:
    """Build CanonicalJob instances for tests."""

    @staticmethod
    def build(*, title: str = "Software Engineer", **overrides) -> CanonicalJob:
        defaults = {
            "title": title,
            "normalized_title": title.lower().strip(),
            "role_family": "software_engineer",
            "skills": ["python", "fastapi"],
            "is_active": True,
            "canonical_hash": "abc123",
        }
        defaults.update(overrides)
        return CanonicalJob(**defaults)
```

### 10.3 Coverage Targets

| Layer | Target | Rationale |
|:---|:---:|:---|
| **Domain models** | 95%+ | Core business logic must be solid |
| **Services** | 90%+ | Orchestration correctness is critical |
| **Repositories** | 85%+ | SQL queries need integration tests |
| **API routes** | 90%+ | Every endpoint tested with auth + errors |
| **Overall** | 90%+ | Already configured in `pyproject.toml` |

---

## 11. Code Quality Standards

### 11.1 Backend (Python)

| Tool | Rule |
|:---|:---|
| **Ruff** | Extended select: adds docstring (`D`) + annotation (`ANN`) checks |
| **Mypy** | `strict = true` — full type safety |
| **Line length** | 100 chars |
| **Import order** | stdlib, then third-party, then local (enforced by Ruff `I`) |
| **Naming** | `snake_case` for everything, `PascalCase` for classes |
| **No implicit Any** | Every function has full type annotations |

### 11.2 Frontend (TypeScript)

| Tool | Rule |
|:---|:---|
| **ESLint** | Next.js recommended + strict TypeScript rules |
| **Prettier** | 2-space indent, single quotes, trailing commas |
| **TypeScript** | `strict: true`, `noUncheckedIndexedAccess: true` |
| **Components** | Named exports only, no default exports |
| **Props** | Interface with JSDoc on every prop |
| **Files** | One component per file, kebab-case filenames |

---

## 12. Sprint-by-Sprint Execution Plan

> Each sprint is 1 week. Total estimated timeline: **8 weeks** for a production-ready rebuild.

### Sprint 1: Foundation (Week 1)
**Goal**: Empty monorepo with all tooling configured. `make dev` starts everything.

- [ ] Create monorepo structure (`hireandtech/`)
- [ ] Initialize backend: `pyproject.toml`, `uv.lock`, Ruff, Mypy, Pytest configs
- [ ] Initialize frontend: `npx create-next-app@latest`, Tailwind, shadcn/ui
- [ ] Docker Compose with PostgreSQL + Redis
- [ ] `Makefile` with `dev`, `stop`, `test`, `lint`, `format` commands
- [ ] GitHub Actions CI for both backend and frontend
- [ ] Root `README.md` with quick start guide
- [ ] `CONTRIBUTING.md` with commit convention + PR template
- [ ] `.env.example` with all required environment variables
- [ ] First ADR: `001-monorepo-structure.md`

**Deliverable**: `git clone` then `make dev` gives API on `:8000/docs` and Web on `:3000`

---

### Sprint 2: Database and Domain Layer (Week 2)
**Goal**: All database models, migrations, and repositories working.

- [ ] `app/db/base.py` — Base model with ID + timestamp mixins
- [ ] `app/domain/jobs.py` — `CanonicalJob`, `Company`, `JobSourceObservation`
- [ ] `app/domain/matches.py` — `JobMatch` (NEW)
- [ ] `app/domain/profiles.py` — `Profile`
- [ ] `app/domain/resumes.py` — `Resume`, `CandidateProfile`
- [ ] `app/domain/applications.py` — `Application` (NEW)
- [ ] Alembic migrations for all tables
- [ ] All repositories with full CRUD
- [ ] Test factories for every domain model
- [ ] Unit tests for all repository methods
- [ ] `docs/database.md` with ER diagram

**Deliverable**: `make migrate` creates all tables. 100% repository test coverage.

---

### Sprint 3: Collection Engine (Week 3)
**Goal**: Background job collection pipeline fully operational.

- [ ] `app/collection/coordinator.py` — Scrape, normalize, persist pipeline
- [ ] `app/collection/normalization.py` — `RawJob` to `NormalizedJob`
- [ ] `app/collection/canonicalization.py` — SHA-256 dedup
- [ ] `app/collection/sources/dice.py` — Dice collector
- [ ] `app/collection/sources/glassdoor.py` — Glassdoor collector (curl_cffi)
- [ ] `app/collection/sources/linkedin.py` — LinkedIn collector
- [ ] `app/collection/sources/hiringcafe.py` — HiringCafe collector
- [ ] `app/collection/circuit_breaker.py` — Redis-backed circuit breaker (NEW)
- [ ] `app/collection/errors.py` — Error hierarchy
- [ ] `app/collection/locks.py` — Redis distributed locks
- [ ] `app/queue/scheduler.py` — Cron scheduler with dynamic query generation
- [ ] `app/queue/tasks/collection.py` — `run_job_collection` task
- [ ] `app/queue/workers/scrape.py` — Independent scrape worker
- [ ] Unit tests for normalization, canonicalization, circuit breaker
- [ ] Integration test: ingest 10 jobs from Dice CLI

**Deliverable**: `arq app.queue.workers.scrape.ScrapeWorkerSettings` collects jobs.

---

### Sprint 4: Search and Matching (Week 4)
**Goal**: Deterministic matching engine + sync search API.

- [ ] `app/services/job_matching.py` — Scoring engine (role, skills, exp, location, freshness)
- [ ] `app/services/job_search.py` — Search orchestration
- [ ] `app/api/v1/routes/jobs.py` — `GET /jobs`, `GET /jobs/recommended`
- [ ] `app/schemas/jobs.py` — Pydantic response models
- [ ] API tests for search with filters, pagination, empty results
- [ ] OpenAPI schema export to `packages/openapi/types.ts`
- [ ] ADR: `004-deterministic-matching-before-ai.md`

**Deliverable**: `GET /api/v1/jobs?query=python&location=NYC` returns canonical jobs.

---

### Sprint 5: Auth, Resumes, Security (Week 5)
**Goal**: Complete authentication, resume upload, rate limiting.

- [ ] `app/auth/verifier.py` — Supabase JWT verification
- [ ] `app/auth/dependencies.py` — FastAPI `Depends()` for current user
- [ ] `app/services/resume_service.py` — Upload, parse, delete
- [ ] `app/services/resume_parser.py` — PDF extraction
- [ ] `app/api/v1/routes/resumes.py` — Resume endpoints
- [ ] `app/api/v1/routes/auth.py` — Auth routes
- [ ] `app/security/rate_limit.py` — Memory + Redis rate limiter
- [ ] `app/security/middleware.py` — IP allowlist, request security
- [ ] API tests for auth flows, resume upload, rate limiting
- [ ] `docs/security.md`

**Deliverable**: Authenticated user can upload resume and get recommendations.

---

### Sprint 6: Async Search and AI Enrichment (Week 6)
**Goal**: Ticket-based async search + AI match enrichment.

- [ ] `app/queue/tasks/search.py` — `run_async_search` task
- [ ] `app/queue/tasks/ai_enrichment.py` — `evaluate_matches` task
- [ ] `app/queue/workers/search.py` — Search worker
- [ ] `app/queue/workers/ai.py` — AI worker
- [ ] `app/api/v1/routes/search.py` — `POST /search`, `GET /search/:id/progress`
- [ ] `app/schemas/search.py` — Search request/progress models
- [ ] Redis key schema for search progress
- [ ] `app/repositories/matches.py` — Job match persistence
- [ ] API tests for async search flow
- [ ] ADR: `006-async-search-ticket-pattern.md`

**Deliverable**: `POST /api/v1/search` returns `search_id`, frontend can poll progress.

---

### Sprint 7: Frontend — Core UI (Week 7)
**Goal**: Professional Next.js frontend with all core pages.

- [ ] Landing page with hero, features, CTA
- [ ] Auth pages (login, signup) with Supabase
- [ ] Dashboard layout (sidebar, header, breadcrumbs)
- [ ] Dashboard overview page (stats, recent matches)
- [ ] Job search page with filters, results grid, pagination
- [ ] Job detail page with match score, skills analysis
- [ ] Resume upload page with drag-and-drop, progress
- [ ] Resume list page with parsed profile summary
- [ ] Recommended jobs page with match scores
- [ ] Profile page with skills, experience
- [ ] Dark mode toggle
- [ ] Responsive design (mobile + desktop)
- [ ] Loading skeletons for every page
- [ ] Error boundaries for every page

**Deliverable**: Full working UI connected to backend API.

---

### Sprint 8: Polish, E2E Tests, Deployment (Week 8)
**Goal**: Production-ready. Ship it.

- [ ] Application tracking page (save, apply, track status)
- [ ] E2E tests with Playwright (5-10 critical flows)
- [ ] Performance audit (Lighthouse 90+)
- [ ] SEO (meta tags, OG images, sitemap)
- [ ] Admin dashboard (collection status, queue health)
- [ ] `docs/deployment.md` — Production deployment guide
- [ ] `docs/api-guide.md` — Hand-written API guide with curl examples
- [ ] `CHANGELOG.md` — v1.0.0 entry
- [ ] Final README polish with screenshots
- [ ] Docker production builds (multi-stage, slim images)
- [ ] Environment-specific configs (local, staging, production)

**Deliverable**: `v1.0.0` — Production-ready platform.

---

## 13. Migration Strategy

### How to Transition from Old to New

| Phase | Action |
|:---|:---|
| **Week 1** | Create new monorepo. Old repos remain untouched. |
| **Week 2-3** | Port backend code module by module. Each port includes cleanup + tests. |
| **Week 4-5** | Port remaining backend features. Old backend still serves production. |
| **Week 6** | New features (async search, AI) built only in new repo. |
| **Week 7** | Build new frontend from scratch (do NOT port `main.tsx`). |
| **Week 8** | Cutover: new repo replaces old. Old repos archived. |

### Data Migration
- PostgreSQL schema is the same so no data migration needed
- Alembic migrations in new repo start from the same baseline
- `make migrate` on new repo is compatible with existing database

### What Gets Thrown Away
- `frontend-ht/src/main.tsx` (1,910 lines) — replaced by proper Next.js pages
- `frontend-ht/src/styles.css` (39KB) — replaced by Tailwind + shadcn/ui
- Hash-based routing — replaced by Next.js App Router
- Manual `fetch()` calls — replaced by generated OpenAPI client

### What Gets Preserved
- All domain models (SQLAlchemy)
- All collector implementations (Dice, Glassdoor, LinkedIn, HiringCafe)
- Matching engine algorithm
- Scheduler and queue infrastructure
- Database migrations and existing data
- Test logic (rewritten with factories)

---

> **Ready to start?** Sprint 1 can begin immediately. Each sprint builds on the previous one, and each has a concrete deliverable that can be tested independently.

---

*Plan created 2026-09-26. Based on codebase audit of `backend-ht` and `frontend-ht`.*
