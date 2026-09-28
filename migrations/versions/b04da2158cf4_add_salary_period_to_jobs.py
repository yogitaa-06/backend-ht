"""add_salary_period_to_jobs

Revision: b04da2158cf4
Parent: 7ab1651e6578
Created: 2026-09-28 06:09:42.966738

Describe data compatibility, ownership restrictions, and downgrade limitations.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b04da2158cf4'
down_revision: str | None = '7ab1651e6578'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the reviewed schema change."""
    op.add_column(
        "jobs",
        sa.Column("salary_period", sa.String(length=32), nullable=True),
        schema="hireandtech",
    )


def downgrade() -> None:
    """Revert only objects owned by this revision."""
    op.drop_column("jobs", "salary_period", schema="hireandtech")
