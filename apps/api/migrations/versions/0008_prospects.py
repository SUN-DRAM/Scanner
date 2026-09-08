"""prospect_batches, prospect_scans tables (admin dashboard v2.8, §11)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-07 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prospect_batches",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "prospect_batches_created_at_idx",
        "prospect_batches",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "prospect_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["prospect_batches.batch_id"],
            name="fk_prospect_scans_batch_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.scan_id"], name="fk_prospect_scans_scan_id"
        ),
        sa.UniqueConstraint("batch_id", "hostname", name="uq_prospect_scans_batch_hostname"),
    )
    op.create_index("prospect_scans_batch_id_idx", "prospect_scans", ["batch_id"])


def downgrade() -> None:
    op.drop_index("prospect_scans_batch_id_idx", table_name="prospect_scans")
    op.drop_table("prospect_scans")
    op.drop_index("prospect_batches_created_at_idx", table_name="prospect_batches")
    op.drop_table("prospect_batches")
