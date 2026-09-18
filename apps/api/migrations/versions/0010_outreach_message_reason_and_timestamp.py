"""outreach_messages.state_reason, outreach_messages.state_changed_at
(outreach orchestrator Stage 1 Step 4 follow-up, contract v3.7, §11)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-17 00:00:01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outreach_messages", sa.Column("state_reason", sa.Text(), nullable=True))
    op.add_column(
        "outreach_messages",
        sa.Column(
            "state_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("outreach_messages", "state_changed_at")
    op.drop_column("outreach_messages", "state_reason")
