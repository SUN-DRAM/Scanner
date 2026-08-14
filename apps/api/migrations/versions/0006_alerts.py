"""add organisation alert preferences, alert_recipients table,
alert_events.send_attempts

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column(
            "timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"
        ),
    )
    op.add_column(
        "organisations",
        sa.Column(
            "quiet_hours_start", sa.String(length=5), nullable=False, server_default="21:00"
        ),
    )
    op.add_column(
        "organisations",
        sa.Column("quiet_hours_end", sa.String(length=5), nullable=False, server_default="08:00"),
    )
    op.add_column(
        "organisations",
        sa.Column("digest_mode", sa.String(length=16), nullable=False, server_default="digest"),
    )
    op.add_column(
        "organisations",
        sa.Column("digest_hour", sa.Integer(), nullable=False, server_default="9"),
    )

    op.add_column(
        "alert_events",
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "alert_events_state_scheduled_for_idx", "alert_events", ["state", "scheduled_for"]
    )

    op.create_table(
        "alert_recipients",
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("unsubscribed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.org_id"], name="fk_alert_recipients_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["monitored_hostnames.monitor_id"],
            name="fk_alert_recipients_monitor_id",
        ),
    )
    op.create_index("alert_recipients_org_id_idx", "alert_recipients", ["org_id"])


def downgrade() -> None:
    op.drop_index("alert_recipients_org_id_idx", table_name="alert_recipients")
    op.drop_table("alert_recipients")

    op.drop_index("alert_events_state_scheduled_for_idx", table_name="alert_events")
    op.drop_column("alert_events", "send_attempts")

    op.drop_column("organisations", "digest_hour")
    op.drop_column("organisations", "digest_mode")
    op.drop_column("organisations", "quiet_hours_end")
    op.drop_column("organisations", "quiet_hours_start")
    op.drop_column("organisations", "timezone")
