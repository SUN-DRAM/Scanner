"""outreach_campaigns.include_weak_prospects (outreach orchestrator Stage 2,
contract v3.10, §11/§7.16)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outreach_campaigns",
        sa.Column(
            "include_weak_prospects",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("outreach_campaigns", "include_weak_prospects")
