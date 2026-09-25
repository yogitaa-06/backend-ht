# Coding Standards

This document outlines the coding conventions and quality‑gate requirements for the **HireAndTech** backend repository.

---
## Language & Style
* **Python 3.11+** – all source files target the latest stable interpreter.
* **PEP 8** – enforced via **ruff** (which includes `ruff format`).  The project uses the **Black** line‑length of 100 characters, but the ruff formatter is the single source of truth.
* **Type Annotations** – full type coverage is required.  Run `uv run mypy app` to verify.  Types should be explicit on public functions, method signatures, and data models.  Use `typing.Protocol` for duck‑typed interfaces (e.g., collectors).
* **Docstrings** – follow the **Google** style.  Every public module, class, function, and method must have a docstring describing purpose, arguments, return values, and raised exceptions.
* **Naming** –
  * Modules & packages: `snake_case`
  * Classes & enums: `PascalCase`
  * Functions, methods, variables: `snake_case`
  * Constants: `UPPER_SNAKE_CASE`
* **Imports** – absolute imports, grouped in the order: standard library, third‑party, local application.  Use `isort` (configured via `ruff`) to enforce ordering.

---
## Linting & Formatting
* **Ruff** – runs on every commit via the pre‑commit hook.  The rule set includes:
  * `F` – pyflakes errors
  * `E` – pycodestyle errors
  * `W` – pycodestyle warnings
  * `B` – bugbear checks
  * `C90` – mccabe complexity (max 10)
  * `I` – import sorting
* **Mypy** – strict mode (`--strict`).  No `# type: ignore` comments are permitted unless absolutely necessary and justified with an inline comment.
* **Pre‑commit** – configured in `.pre-commit-config.yaml`.  The hook runs `ruff --fix`, `ruff format`, and `mypy`.

---
## Testing
* **pytest** – the test suite lives under `tests/`.  Tests must be deterministic and should not hit external services; use fixtures or HTTP mock libraries (`respx`, `playwright` fixtures) for collectors.
* **Coverage** – target 90 % line coverage for business‑logic modules (`app/jobs`, `app/repositories`).  Run `uv run coverage run -m pytest && uv run coverage report`.
* **Async Tests** – use `pytest-asyncio` and `anyio` for async support.  All async functions should be tested with an event loop.

---
## Git Workflow
* Branch naming: `feature/<short-description>`, `bugfix/<short-description>`, `doc/<topic>`.
* Pull Requests must pass all CI checks (ruff, mypy, pytest, migrations) before merging.
* Commits should be atomic and include a concise title (<50 chars) followed by an optional body.

---
## Review Checklist
- [ ] Code follows PEP 8 and passes `ruff`.
- [ ] All new/modified symbols are type‑annotated and pass `mypy`.
- [ ] Public API has docstrings.
- [ ] Tests added with ≥ 90 % coverage for changed logic.
- [ ] No new `# noqa` or `# type: ignore` without justification.
- [ ] `pre-commit` passes locally.

---
*All statements reflect the current repository implementation; no code modifications are performed by this document.*
