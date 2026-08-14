"""create monitored_hostnames table, add scans.monitor_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitored_hostnames",
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="443"),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_scan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_grade", sa.String(length=2), nullable=True),
        sa.Column("last_score", sa.Integer(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cert_not_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.org_id"], name="fk_monitored_hostnames_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["last_scan_id"], ["scans.scan_id"], name="fk_monitored_hostnames_last_scan_id"
        ),
        sa.UniqueConstraint(
            "org_id", "hostname", "port", name="uq_monitored_hostnames_org_hostname_port"
        ),
    )
    op.create_index("monitored_hostnames_org_id_idx", "monitored_hostnames", ["org_id"])
    op.create_index("monitored_hostnames_state_idx", "monitored_hostnames", ["state"])

    op.add_column("scans", sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_scans_monitor_id", "scans", "monitored_hostnames", ["monitor_id"], ["monitor_id"]
    )
    op.create_index(
        "scans_monitor_id_idx", "scans", ["monitor_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_index("scans_monitor_id_idx", table_name="scans")
    op.drop_constraint("fk_scans_monitor_id", "scans", type_="foreignkey")
    op.drop_column("scans", "monitor_id")

    op.drop_index("monitored_hostnames_state_idx", table_name="monitored_hostnames")
    op.drop_index("monitored_hostnames_org_id_idx", table_name="monitored_hostnames")
    op.drop_table("monitored_hostnames")
