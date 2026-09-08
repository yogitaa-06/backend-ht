"""Create persistent IP rules and append-oriented security audit events.

Revision: 0003_ip_security
Parent: 0002_profiles
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_ip_security"
down_revision: str | None = "0002_profiles"
branch_labels: str | None = None
depends_on: str | None = None

AUDIT_EVENT_TYPES = (
    "IP_ACCESS_DENIED",
    "IP_RULE_CREATED",
    "IP_RULE_UPDATED",
    "IP_RULE_DISABLED",
    "IP_RULE_DELETED",
    "IP_EMERGENCY_BYPASS_USED",
)


def upgrade() -> None:
    """Create administrator-managed rules and non-public audit history."""
    op.create_table(
        "ip_access_rules",
        sa.Column("cidr", postgresql.CIDR(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["hireandtech.profiles.id"],
            name="fk_ip_access_rules_created_by_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_access_rules"),
        sa.UniqueConstraint("cidr", name="uq_ip_access_rules_cidr"),
        schema="hireandtech",
    )
    op.create_index(
        "ix_ip_access_rules_created_by",
        "ip_access_rules",
        ["created_by"],
        schema="hireandtech",
    )
    op.create_index(
        "ix_ip_access_rules_enabled_cidr",
        "ip_access_rules",
        ["cidr"],
        schema="hireandtech",
        postgresql_using="gist",
        postgresql_where=sa.text("enabled"),
    )
    op.create_table(
        "security_audit_events",
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "event_type",
            sa.Enum(
                *AUDIT_EVENT_TYPES,
                name="security_audit_event_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("request_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["hireandtech.profiles.id"],
            name="fk_security_audit_events_actor_user_id_profiles",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_security_audit_events"),
        schema="hireandtech",
    )
    op.create_index(
        "ix_security_audit_events_created_at_id",
        "security_audit_events",
        ["created_at", "id"],
        schema="hireandtech",
    )
    op.create_index(
        "ix_security_audit_events_event_type",
        "security_audit_events",
        ["event_type"],
        schema="hireandtech",
    )
    op.execute("REVOKE ALL ON TABLE hireandtech.ip_access_rules FROM PUBLIC")
    op.execute("REVOKE ALL ON TABLE hireandtech.security_audit_events FROM PUBLIC")


def downgrade() -> None:
    """Remove only Phase 4 audit history and IP rules."""
    op.drop_table("security_audit_events", schema="hireandtech")
    op.drop_table("ip_access_rules", schema="hireandtech")
