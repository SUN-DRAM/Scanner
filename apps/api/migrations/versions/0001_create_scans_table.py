"""create scans table

Revision ID: 0001
Revises:
Create Date: 2026-08-10 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scans",
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("public_slug", sa.String(length=12), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="443"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("overall_grade", sa.String(length=2), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint("uq_scans_public_slug", "scans", ["public_slug"])
    op.create_index(
        "scans_hostname_created_idx",
        "scans",
        ["hostname", sa.text("created_at DESC")],
    )
    op.create_index("scans_status_idx", "scans", ["status"])


def downgrade() -> None:
    op.drop_index("scans_status_idx", table_name="scans")
    op.drop_index("scans_hostname_created_idx", table_name="scans")
    op.drop_constraint("uq_scans_public_slug", "scans", type_="unique")
    op.drop_table("scans")
