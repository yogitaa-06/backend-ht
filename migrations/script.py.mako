"""${message}

Revision: ${up_revision}
Parent: ${down_revision | comma,n}
Created: ${create_date}

Describe data compatibility, ownership restrictions, and downgrade limitations.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Apply the reviewed schema change."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert only objects owned by this revision."""
    ${downgrades if downgrades else "pass"}
