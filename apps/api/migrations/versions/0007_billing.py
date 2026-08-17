"""subscriptions, invoices, billing_events tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-17 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column(
            "subscription_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_code", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="trialing"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("provider_subscription_id", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.org_id"], name="fk_subscriptions_org_id"
        ),
        sa.UniqueConstraint("org_id", name="uq_subscriptions_org_id"),
    )
    op.create_index("subscriptions_org_id_idx", "subscriptions", ["org_id"])

    op.create_table(
        "invoices",
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="paid"),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.String(length=500), nullable=True),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("place_of_supply", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.org_id"], name="fk_invoices_org_id"),
        sa.UniqueConstraint("number", name="uq_invoices_number"),
    )
    op.create_index("invoices_org_id_idx", "invoices", ["org_id", sa.text("issued_at DESC")])

    op.create_table(
        "billing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event_id"),
    )


def downgrade() -> None:
    op.drop_table("billing_events")

    op.drop_index("invoices_org_id_idx", table_name="invoices")
    op.drop_table("invoices")

    op.drop_index("subscriptions_org_id_idx", table_name="subscriptions")
    op.drop_table("subscriptions")
