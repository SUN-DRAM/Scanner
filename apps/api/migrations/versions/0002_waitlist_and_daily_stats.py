"""create waitlist_signups and daily_stats tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.scan_id"], name="fk_waitlist_signups_scan_id"),
    )
    op.create_index("waitlist_signups_scan_id_idx", "waitlist_signups", ["scan_id"])
    op.create_index(
        "waitlist_signups_created_at_idx",
        "waitlist_signups",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "daily_stats",
        sa.Column("day", sa.Date(), primary_key=True, nullable=False),
        sa.Column("scans_started", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scans_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scans_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_link_opens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waitlist_signups", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("daily_stats")
    op.drop_index("waitlist_signups_created_at_idx", table_name="waitlist_signups")
    op.drop_index("waitlist_signups_scan_id_idx", table_name="waitlist_signups")
    op.drop_table("waitlist_signups")
