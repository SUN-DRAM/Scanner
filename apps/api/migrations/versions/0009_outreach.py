"""outreach_campaigns, outreach_prospects, outreach_domains,
outreach_messages, outreach_suppressions tables (outreach orchestrator
Stage 1, contract v3.6, §11/§7.15)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-17 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outreach_campaigns",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "outreach_prospects",
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_name", sa.Text(), nullable=False),
        sa.Column("agency_website", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("icp_grade", sa.String(length=24), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column(
            "do_not_contact", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["outreach_campaigns.campaign_id"],
            name="fk_outreach_prospects_campaign_id",
            # No ON DELETE: a campaign with prospects must be emptied
            # explicitly before it can be deleted, never silently cascaded.
        ),
        sa.UniqueConstraint(
            "campaign_id", "contact_email", name="uq_outreach_prospects_campaign_email"
        ),
    )
    op.create_index(
        "outreach_prospects_campaign_state_idx",
        "outreach_prospects",
        ["campaign_id", "state"],
    )

    op.create_table(
        "outreach_domains",
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column(
            "relationship", sa.String(length=16), nullable=False, server_default="client"
        ),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scan_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scan_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["prospect_id"],
            ["outreach_prospects.prospect_id"],
            name="fk_outreach_domains_prospect_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.scan_id"],
            name="fk_outreach_domains_scan_id",
            # No ON DELETE (default RESTRICT), deliberately not SET NULL —
            # see CONTRACT.md §11. A COMPLETED domain must never end up
            # pointing at a deleted scan.
        ),
        sa.UniqueConstraint(
            "prospect_id", "hostname", name="uq_outreach_domains_prospect_hostname"
        ),
    )
    op.create_index(
        "outreach_domains_prospect_state_idx",
        "outreach_domains",
        ["prospect_id", "state"],
    )

    op.create_table(
        "outreach_messages",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hook_code", sa.String(length=48), nullable=False),
        sa.Column("hook_domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hook_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hook_finding_code", sa.String(length=64), nullable=True),
        sa.Column(
            "secondary_domain_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
        sa.Column("template_variant", sa.SmallInteger(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "attachment_scan_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
        sa.Column("gmail_draft_id", sa.Text(), nullable=True),
        sa.Column("gmail_message_id", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["prospect_id"],
            ["outreach_prospects.prospect_id"],
            name="fk_outreach_messages_prospect_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hook_domain_id"],
            ["outreach_domains.domain_id"],
            name="fk_outreach_messages_hook_domain_id",
            # No ON DELETE: this row is only ever removed via the same
            # prospect-cascade that removes its hook_domain_id's own row,
            # not independently.
        ),
        sa.ForeignKeyConstraint(
            ["hook_scan_id"],
            ["scans.scan_id"],
            name="fk_outreach_messages_hook_scan_id",
            # No ON DELETE (default RESTRICT) — same reasoning as
            # outreach_domains.scan_id above; NOT NULL here rules out
            # SET NULL regardless.
        ),
        sa.UniqueConstraint("prospect_id", name="uq_outreach_messages_prospect_id"),
    )

    op.create_table(
        "outreach_suppressions",
        sa.Column("email", sa.String(length=320), primary_key=True, nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("outreach_suppressions")
    op.drop_table("outreach_messages")
    op.drop_index("outreach_domains_prospect_state_idx", table_name="outreach_domains")
    op.drop_table("outreach_domains")
    op.drop_index("outreach_prospects_campaign_state_idx", table_name="outreach_prospects")
    op.drop_table("outreach_prospects")
    op.drop_table("outreach_campaigns")
