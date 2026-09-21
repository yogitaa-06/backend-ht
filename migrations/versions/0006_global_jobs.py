"""Add canonical global jobs for scheduled source collection.

Revision: 0006_global_jobs
Parent: 0005_phase5_hardening
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_global_jobs"
down_revision: str | None = "0005_phase5_hardening"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "global_jobs",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_job_id", sa.String(length=512), nullable=False),
        sa.Column("job_title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("role_family", sa.String(length=64), nullable=False),
        sa.Column("company", sa.String(length=500)),
        sa.Column("location", sa.String(length=500)),
        sa.Column("job_url", sa.String(length=2048)),
        sa.Column("description", sa.Text()),
        sa.Column("salary_text", sa.String(length=500)),
        sa.Column("employment_type", sa.String(length=100)),
        sa.Column("remote", sa.Boolean()),
        sa.Column(
            "skills", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("experience_min_years", sa.Integer()),
        sa.Column("experience_max_years", sa.Integer()),
        sa.Column("experience_text", sa.String(length=500)),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("content_hash", sa.String(length=128)),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "experience_min_years IS NULL OR experience_min_years >= 0",
            name="ck_global_jobs_min_experience_nonnegative",
        ),
        sa.CheckConstraint(
            "experience_max_years IS NULL OR experience_max_years >= 0",
            name="ck_global_jobs_max_experience_nonnegative",
        ),
        sa.CheckConstraint(
            "experience_max_years IS NULL OR experience_min_years IS NULL "
            "OR experience_max_years >= experience_min_years",
            name="ck_global_jobs_experience_ordered",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_global_jobs"),
        sa.UniqueConstraint("source", "external_job_id", name="uq_global_jobs_source_external_id"),
        schema="hireandtech",
    )
    for name, columns in {
        "ix_global_jobs_source_active": ["source", "is_active"],
        "ix_global_jobs_active_posted": ["is_active", "posted_at"],
        "ix_global_jobs_role_family_active": ["role_family", "is_active"],
        "ix_global_jobs_experience": ["experience_min_years", "experience_max_years"],
        "ix_global_jobs_location": ["location"],
    }.items():
        op.create_index(name, "global_jobs", columns, schema="hireandtech")
    op.execute("REVOKE ALL ON TABLE hireandtech.global_jobs FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("global_jobs", schema="hireandtech")
