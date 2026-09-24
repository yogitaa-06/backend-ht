"""Add canonical companies, jobs, and source observations.

Revision: 0007_canonical_jobs
Parent: 0006_global_jobs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_canonical_jobs"
down_revision: str | None = "0006_global_jobs"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("website_url", sa.String(length=2048)),
        sa.Column("domain", sa.String(length=255)),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("normalized_name", name="uq_companies_normalized_name"),
        schema="hireandtech",
    )
    op.create_index("ix_companies_domain", "companies", ["domain"], schema="hireandtech")

    op.create_table(
        "jobs",
        sa.Column("company_id", sa.Uuid()),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("location", sa.String(length=500)),
        sa.Column("normalized_location", sa.String(length=500)),
        sa.Column("employment_type", sa.String(length=100)),
        sa.Column("remote_type", sa.String(length=32)),
        sa.Column(
            "skills", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("experience_min_years", sa.Integer()),
        sa.Column("experience_max_years", sa.Integer()),
        sa.Column("experience_text", sa.String(length=500)),
        sa.Column("role_family", sa.String(length=64), nullable=False),
        sa.Column("seniority", sa.String(length=64)),
        sa.Column("salary_min", sa.Numeric(precision=14, scale=2)),
        sa.Column("salary_max", sa.Numeric(precision=14, scale=2)),
        sa.Column("salary_currency", sa.String(length=3)),
        sa.Column("salary_text", sa.String(length=500)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "experience_min_years IS NULL OR experience_min_years >= 0",
            name=op.f("ck_jobs_min_experience_nonnegative"),
        ),
        sa.CheckConstraint(
            "experience_max_years IS NULL OR experience_max_years >= 0",
            name=op.f("ck_jobs_max_experience_nonnegative"),
        ),
        sa.CheckConstraint(
            "experience_max_years IS NULL OR experience_min_years IS NULL "
            "OR experience_max_years >= experience_min_years",
            name=op.f("ck_jobs_experience_ordered"),
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name=op.f("ck_jobs_salary_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["hireandtech.companies.id"],
            name="fk_jobs_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        schema="hireandtech",
    )
    for name, columns in {
        "ix_jobs_company_id": ["company_id"],
        "ix_jobs_canonical_hash": ["canonical_hash"],
        "ix_jobs_normalized_title_location": ["normalized_title", "normalized_location"],
        "ix_jobs_active_posted_at": ["is_active", "posted_at"],
        "ix_jobs_active_last_seen_at": ["is_active", "last_seen_at"],
        "ix_jobs_role_family_active": ["role_family", "is_active"],
    }.items():
        op.create_index(name, "jobs", columns, schema="hireandtech")

    op.create_table(
        "job_sources",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_job_id", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.String(length=2048)),
        sa.Column("source_posted_at", sa.DateTime(timezone=True)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
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
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "raw_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["hireandtech.jobs.id"],
            name="fk_job_sources_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_sources"),
        sa.UniqueConstraint("source", "source_job_id", name="uq_job_sources_source_job_id"),
        schema="hireandtech",
    )
    op.create_index("ix_job_sources_job_id", "job_sources", ["job_id"], schema="hireandtech")
    op.create_index(
        "ix_job_sources_source_url",
        "job_sources",
        ["source", "source_url"],
        schema="hireandtech",
    )
    op.create_index(
        "ix_job_sources_source_last_seen_at",
        "job_sources",
        ["source", "last_seen_at"],
        schema="hireandtech",
    )

    # Existing global_jobs rows remain authoritative for the current API. Backfill
    # one canonical job per legacy row, which cannot introduce unsafe cross-source
    # merges, and retain the same UUID as an auditable transition mapping.
    op.execute(
        """
        INSERT INTO hireandtech.companies (name, normalized_name)
        SELECT min(btrim(company)), lower(regexp_replace(btrim(company), '\\s+', ' ', 'g'))
        FROM hireandtech.global_jobs
        WHERE company IS NOT NULL AND btrim(company) <> ''
        GROUP BY lower(regexp_replace(btrim(company), '\\s+', ' ', 'g'))
        ON CONFLICT (normalized_name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO hireandtech.jobs (
            id, company_id, title, normalized_title, description, location,
            normalized_location, employment_type, remote_type, skills,
            experience_min_years, experience_max_years, experience_text,
            role_family, salary_text, posted_at, first_seen_at, last_seen_at,
            is_active, canonical_hash, created_at, updated_at
        )
        SELECT
            global_job.id,
            company.id,
            global_job.job_title,
            global_job.normalized_title,
            global_job.description,
            global_job.location,
            CASE WHEN global_job.location IS NULL THEN NULL
                 ELSE lower(regexp_replace(btrim(global_job.location), '\\s+', ' ', 'g')) END,
            global_job.employment_type,
            CASE WHEN global_job.remote IS TRUE THEN 'remote'
                 WHEN global_job.remote IS FALSE THEN 'on_site' END,
            global_job.skills,
            global_job.experience_min_years,
            global_job.experience_max_years,
            global_job.experience_text,
            global_job.role_family,
            global_job.salary_text,
            global_job.posted_at,
            global_job.first_seen_at,
            global_job.last_seen_at,
            global_job.is_active,
            md5(global_job.id::text) || md5(global_job.id::text || '-canonical'),
            global_job.created_at,
            global_job.updated_at
        FROM hireandtech.global_jobs AS global_job
        LEFT JOIN hireandtech.companies AS company
          ON company.normalized_name =
             lower(regexp_replace(btrim(global_job.company), '\\s+', ' ', 'g'))
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO hireandtech.job_sources (
            job_id, source, source_job_id, source_url, source_posted_at,
            first_seen_at, last_seen_at, scraped_at, content_hash, is_active,
            raw_data, created_at, updated_at
        )
        SELECT
            id, source, external_job_id, job_url, posted_at, first_seen_at,
            last_seen_at, scraped_at,
            CASE WHEN content_hash ~ '^[0-9a-f]{64}$' THEN content_hash
                 ELSE md5(id::text) || md5(id::text || '-content') END,
            is_active, jsonb_build_object('legacy_global_job_id', id), created_at, updated_at
        FROM hireandtech.global_jobs
        ON CONFLICT (source, source_job_id) DO NOTHING
        """
    )

    for table in ("companies", "jobs", "job_sources"):
        op.execute(f"REVOKE ALL ON TABLE hireandtech.{table} FROM PUBLIC")


def downgrade() -> None:
    # global_jobs remains untouched and continues serving the existing APIs.
    op.drop_table("job_sources", schema="hireandtech")
    op.drop_table("jobs", schema="hireandtech")
    op.drop_table("companies", schema="hireandtech")
