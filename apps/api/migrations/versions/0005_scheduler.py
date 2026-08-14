"""add monitored_hostnames.consecutive_failures, create alert_events table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monitored_hostnames",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "alert_events",
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.org_id"], name="fk_alert_events_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"], ["monitored_hostnames.monitor_id"], name="fk_alert_events_monitor_id"
        ),
    )
    op.create_index("alert_events_dedupe_key_idx", "alert_events", ["dedupe_key"])
    op.create_index("alert_events_org_id_idx", "alert_events", ["org_id"])


def downgrade() -> None:
    op.drop_index("alert_events_org_id_idx", table_name="alert_events")
    op.drop_index("alert_events_dedupe_key_idx", table_name="alert_events")
    op.drop_table("alert_events")

    op.drop_column("monitored_hostnames", "consecutive_failures")
