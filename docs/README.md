# Documentation Index

This repository uses a **consolidated documentation** layout with one comprehensive Markdown file per major area.

## Files

- **api.md** – Complete API documentation (endpoints, auth, error handling).
- **architecture.md** – System architecture overview, current & target designs, component diagrams, scalability and failure handling.
- **ingestion.md** – Job ingestion pipeline: collection, normalization, canonicalization, deduplication, freshness, persistence, scheduling, and queue interactions.
- **scrapers.md** – Detailed scraper implementations for Dice, LinkedIn, Glassdoor, HiringCafe; collector standards, extracted fields, error handling, and how to add a new source.
- **database.md** – Database schema, tables, relationships, deduplication logic, freshness strategy.
- **coding-standards.md** – Coding conventions, style guides, linting, type checking, testing practices.
- **security.md** – Authentication, authorization, IP security, secret management, audit logging.
- **development.md** – Local setup, configuration, testing, Git workflow, common commands.
- **deployment.md** – Container build, deployment steps, migrations, production considerations.
- **troubleshooting.md** – Common problems, diagnostics, and resolutions.
- **scraper-debug-workflow.md** – Step‑by‑step, beginner‑friendly trace of the scraper execution flow.

These files are located directly under `docs/`. The older per‑topic files have been removed in favor of this simplified structure.
