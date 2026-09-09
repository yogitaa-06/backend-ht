"""Create private resume metadata and structured candidate profiles.

Revision: 0004_resumes
Parent: 0003_ip_security
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_resumes"
down_revision: str | None = "0003_ip_security"
branch_labels: str | None = None
depends_on: str | None = None

RESUME_STATUSES = (
    "uploaded",
    "parsing",
    "parsed",
    "parse_failed",
    "deleted",
)


def upgrade() -> None:
    """Create private resume and candidate-profile persistence."""

    op.create_table(
        "resumes",
        sa.Column("owner_profile_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_bucket", sa.String(length=63), nullable=False),
        sa.Column(
            "storage_object_key",
            sa.String(length=1024),
            nullable=False,
        ),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *RESUME_STATUSES,
                name="resume_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'uploaded'"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("parse_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_resumes_resume_size_positive",
        ),
        sa.CheckConstraint(
            "char_length(sha256) = 64",
            name="ck_resumes_resume_sha256_length",
        ),
        sa.CheckConstraint(
            "content_type = 'application/pdf'",
            name="ck_resumes_resume_pdf_content_type",
        ),
        sa.CheckConstraint(
            """
            (status = 'deleted' AND deleted_at IS NOT NULL)
            OR
            (status <> 'deleted' AND deleted_at IS NULL)
            """,
            name="ck_resumes_resume_deleted_state_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_profile_id"],
            ["hireandtech.profiles.id"],
            name="fk_resumes_owner_profile_id_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_resumes",
        ),
        sa.UniqueConstraint(
            "storage_object_key",
            name="uq_resumes_storage_object_key",
        ),
        sa.UniqueConstraint(
            "id",
            "owner_profile_id",
            name="uq_resumes_id_owner_profile_id",
        ),
        schema="hireandtech",
    )

    op.create_index(
        "ix_resumes_owner_created_id",
        "resumes",
        ["owner_profile_id", "created_at", "id"],
        schema="hireandtech",
    )
    op.create_index(
        "ix_resumes_owner_status",
        "resumes",
        ["owner_profile_id", "status"],
        schema="hireandtech",
    )
    op.create_index(
        "ix_resumes_owner_sha256",
        "resumes",
        ["owner_profile_id", "sha256"],
        schema="hireandtech",
    )

    op.create_table(
        "candidate_profiles",
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("owner_profile_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("current_title", sa.String(length=200), nullable=True),
        sa.Column("professional_summary", sa.Text(), nullable=True),
        sa.Column(
            "years_of_experience",
            sa.Numeric(precision=4, scale=1),
            nullable=True,
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "employment_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "education",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "certifications",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "languages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "raw_parser_output",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            """
            years_of_experience IS NULL
            OR
            (
                years_of_experience >= 0
                AND years_of_experience <= 80
            )
            """,
            name="ck_candidate_profiles_candidate_years_of_experience_range",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(skills) = 'array'",
            name="ck_candidate_profiles_candidate_skills_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(employment_history) = 'array'",
            name="ck_candidate_profiles_candidate_employment_history_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(education) = 'array'",
            name="ck_candidate_profiles_candidate_education_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(certifications) = 'array'",
            name="ck_candidate_profiles_candidate_certifications_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(languages) = 'array'",
            name="ck_candidate_profiles_candidate_languages_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(raw_parser_output) = 'object'",
            name="ck_candidate_profiles_candidate_raw_parser_output_object",
        ),
        sa.ForeignKeyConstraint(
            ["owner_profile_id"],
            ["hireandtech.profiles.id"],
            name="fk_candidate_profiles_owner_profile_id_profiles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resume_id", "owner_profile_id"],
            [
                "hireandtech.resumes.id",
                "hireandtech.resumes.owner_profile_id",
            ],
            name="fk_candidate_profiles_resume_owner_resumes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_candidate_profiles",
        ),
        sa.UniqueConstraint(
            "resume_id",
            name="uq_candidate_profiles_resume_id",
        ),
        schema="hireandtech",
    )

    op.create_index(
        "ix_candidate_profiles_owner_created_id",
        "candidate_profiles",
        ["owner_profile_id", "created_at", "id"],
        schema="hireandtech",
    )

    op.execute("REVOKE ALL ON TABLE hireandtech.resumes FROM PUBLIC")
    op.execute("REVOKE ALL ON TABLE hireandtech.candidate_profiles FROM PUBLIC")


def downgrade() -> None:
    """Remove only Phase 5 resume persistence."""

    op.drop_table(
        "candidate_profiles",
        schema="hireandtech",
    )
    op.drop_table(
        "resumes",
        schema="hireandtech",
    )
