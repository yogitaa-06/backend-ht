"""Create administrator-provisioned application profiles.

Revision: 0002_profiles
Parent: 0001_persistence_foundation

Profiles link Supabase subject UUIDs to local application authorization. They do not
reference provider-managed schemas and never contain passwords or provider secrets.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_profiles"
down_revision: str | None = "0001_persistence_foundation"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the local profile authorization boundary."""
    op.create_table(
        "profiles",
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "employee",
                "admin",
                name="profile_role",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="employee",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("auth_user_id", name=op.f("uq_profiles_auth_user_id")),
        sa.UniqueConstraint("email", name=op.f("uq_profiles_email")),
        schema="hireandtech",
    )
    op.execute("REVOKE ALL ON TABLE hireandtech.profiles FROM PUBLIC")


def downgrade() -> None:
    """Remove only the profiles table owned by this revision."""
    op.drop_table("profiles", schema="hireandtech")
