"""Harden resume integrity for concurrent and non-ORM writers.

Revision: 0005_phase5_hardening
Parent: 0004_resumes
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase5_hardening"
down_revision: str | None = "0004_resumes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        schema="hireandtech",
    )
    op.create_check_constraint(
        "ck_resumes_resume_sha256_lower_hex",
        "resumes",
        "sha256 ~ '^[0-9a-f]{64}$'",
        schema="hireandtech",
    )
    op.create_table(
        "resume_storage_cleanups",
        sa.Column("owner_profile_id", sa.Uuid(), nullable=False),
        sa.Column("storage_bucket", sa.String(length=63), nullable=False),
        sa.Column("storage_object_key", sa.String(length=1024), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
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
            "attempts >= 0",
            name="ck_resume_storage_cleanups_resume_cleanup_attempts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["owner_profile_id"],
            ["hireandtech.profiles.id"],
            name="fk_resume_storage_cleanups_owner_profile_id_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resume_storage_cleanups"),
        sa.UniqueConstraint(
            "storage_object_key",
            name="uq_resume_storage_cleanups_storage_object_key",
        ),
        schema="hireandtech",
    )
    op.create_index(
        "ix_resume_storage_cleanups_available_at_id",
        "resume_storage_cleanups",
        ["available_at", "id"],
        schema="hireandtech",
    )
    op.execute("REVOKE ALL ON TABLE hireandtech.resume_storage_cleanups FROM PUBLIC")
    op.create_check_constraint(
        "ck_resumes_resume_filename_not_blank",
        "resumes",
        "char_length(btrim(original_filename)) > 0",
        schema="hireandtech",
    )
    op.create_check_constraint(
        "ck_resumes_resume_parse_error_state_consistent",
        "resumes",
        """
        (status = 'parse_failed' AND parse_error_code IS NOT NULL)
        OR
        (status <> 'parse_failed' AND parse_error_code IS NULL)
        """,
        schema="hireandtech",
    )
    op.create_check_constraint(
        "ck_resumes_resume_version_positive",
        "resumes",
        "version > 0",
        schema="hireandtech",
    )


def downgrade() -> None:
    op.drop_table("resume_storage_cleanups", schema="hireandtech")
    op.drop_constraint(
        "ck_resumes_resume_version_positive",
        "resumes",
        schema="hireandtech",
        type_="check",
    )
    op.drop_constraint(
        "ck_resumes_resume_parse_error_state_consistent",
        "resumes",
        schema="hireandtech",
        type_="check",
    )
    op.drop_constraint(
        "ck_resumes_resume_filename_not_blank",
        "resumes",
        schema="hireandtech",
        type_="check",
    )
    op.drop_constraint(
        "ck_resumes_resume_sha256_lower_hex",
        "resumes",
        schema="hireandtech",
        type_="check",
    )
    op.drop_column("resumes", "version", schema="hireandtech")
