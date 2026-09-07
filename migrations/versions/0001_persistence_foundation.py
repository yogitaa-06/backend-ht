"""
Establish private persistence bookkeeping without creating domain tables.

Revision: 0001_persistence_foundation
Parent: none

The environment bootstraps hireandtech before Alembic creates its version table.
Downgrade deliberately preserves the schema and its restrictive privileges: deleting
the schema or granting public access is unsafe even when no domain revisions remain.
"""

from alembic import op

revision: str = "0001_persistence_foundation"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Keep the application schema and migration history inaccessible to PUBLIC."""
    op.execute("REVOKE ALL ON SCHEMA hireandtech FROM PUBLIC")
    op.execute("REVOKE ALL ON TABLE hireandtech.alembic_version FROM PUBLIC")


def downgrade() -> None:
    """Remove the revision stamp only; retain schema and security restrictions."""
