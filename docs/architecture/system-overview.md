# System Overview

This document provides a high‑level view of the **HireAndTech Backend** as it exists today.

```mermaid
flowchart LR
    subgraph API[FastAPI Application]
        A[Root router (/) ]
        B[Versioned API (/api/v1)]
    end
    subgraph Workers[ARQ Worker]
        C[Collection Worker]
    end
    subgraph Redis[(Redis)]
        D[Task queue & lock store]
    end
    subgraph DB[(PostgreSQL)]
        E[global_jobs table]
        F[companies table]
        G[profiles & IP rules]
    end
    A --> B
    B -->|calls| D
    D --> C
    C -->|fetches source data| Source[Job Sources]
    Source -->|raw jobs| C
    C -->|produces RawSourceJob| Normalizer[Normalization]
    Normalizer -->|NormalizedJob| DB
    DB -->|canonical jobs| API
```

**Key components**
- **FastAPI** – HTTP API, authentication, health checks.
- **ARQ + Redis** – background task queue and distributed lock store.
- **PostgreSQL** – async SQLAlchemy ORM for persistence.
- **Job Sources** – Dice, LinkedIn, HiringCafe, Glassdoor (blocked).
- **Normalization** – `app/jobs/normalization.py` turns `RawSourceJob` into `NormalizedJob`.
- **Canonical ingestion** – `app/jobs/canonicalization.py` writes canonical rows.

The diagram shows the current runtime wiring; future target components are documented separately.
