# Deployment Documentation

This document explains how to build, containerize, and deploy the **HireAndTech** backend in a production environment.

## 1. Container Image
The project ships a Dockerfile located at the repository root. The image is based on **python:3.11-slim** and contains:
* The application code (`/app`).
* All runtime dependencies installed via **uv** (`uv sync --system`).
* **Playwright** browsers (`uv run playwright install --with-deps`).

### Build Image
```bash
# From the repository root
docker build -t hireandtech-backend:latest .
```
The build performs a multi‑stage process to keep the final image size < 200 MB.

## 2. Environment Variables
All configuration is provided through environment variables (see `app/core/config.py`). Required variables for production:
| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://user:pass@host:5432/hireandtech`). |
| `JWT_SECRET_KEY` | Secret used to sign JWTs (must be at least 32 characters). |
| `HOST` | Host address the service binds to (default `0.0.0.0`). |
| `PORT` | Port number (default `8000`). |
| `IP_ALLOWLIST_ENABLED` | `true`/`false` – enable IP allow‑list middleware. |
| `RATE_LIMIT_ENABLED` | `true`/`false` – enable rate limiting. |
| `LOG_LEVEL` | Logging level (`INFO`, `DEBUG`, etc.). |

Optional variables for observability:
* `OTEL_EXPORTER_OTLP_ENDPOINT`
* `SENTRY_DSN`

## 3. Database Migrations
The service uses **Alembic** for schema evolution.
```bash
# Inside the running container (or on the host with the same env)
uv run alembic upgrade head
```
Migrations are version‑controlled under `alembic/`.

## 4. Running in Production
Typical orchestration uses **Kubernetes** or **Docker‑Compose**. Below is a minimal `docker‑compose.yml` example:
```yaml
version: "3.9"
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: hireandtech
      POSTGRES_USER: hireandtech
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
  backend:
    image: hireandtech-backend:latest
    depends_on:
      - db
    environment:
      DATABASE_URL: postgresql+asyncpg://hireandtech:${POSTGRES_PASSWORD}@db:5432/hireandtech
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      LOG_LEVEL: INFO
    ports:
      - "8000:8000"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
volumes:
  pgdata:
```
Deploy with `docker compose up -d`.

## 5. Observability & Health Checks
* **Liveness probe** – `GET /health`
* **Readiness probe** – `GET /health/ready`
* **Metrics** – Exposed at `/metrics` (Prometheus format) via `starlette_exporter` (enabled in `Settings`).
* **Logging** – JSON‑structured logs written to stdout. Forward to your log aggregation system (e.g., Loki, ELK).

## 6. Scaling
The service is stateless except for the rate‑limit store (in‑memory by default). For horizontal scaling:
1. Deploy a **shared Redis** store and configure `RateLimitStore` implementation (replace `BoundedMemoryRateLimitStore`).
2. Ensure the database connection pool (`SQLALCHEMY_DATABASE_URL`) allows the desired number of concurrent connections.
3. Use a load balancer (NGINX, Envoy) to distribute traffic.

## 7. Security Hardening
* Run the container with a non‑root user (the Dockerfile sets `USER appuser`).
* Enable **read‑only** filesystem for `/app`.
* Use **Docker secrets** for `JWT_SECRET_KEY` and database credentials.
* Enforce HTTPS at the edge (NGINX termination). The service itself runs HTTP only on the internal network.

---
*All statements reflect the current repository implementation; no code changes are performed by this document.*
