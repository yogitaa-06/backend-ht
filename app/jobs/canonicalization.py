"""Conservative, source-independent canonical job fingerprints."""

from __future__ import annotations

import hashlib

from app.jobs.normalization import NormalizedJob


def build_canonical_hash(job: NormalizedJob) -> str:
    """Build an indexed candidate key without treating it as proof of identity.

    Equal company, title, location, and posting date narrow future cross-source
    searches, but do not prove two employer requisitions are the same opening.
    Phase 1A therefore never merges distinct Dice IDs from this hash alone.
    """
    posted_date = job.posted_at.date().isoformat() if job.posted_at else ""
    value = "\0".join(
        (
            job.normalized_company or "",
            job.normalized_title,
            job.normalized_location or "",
            posted_date,
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()
