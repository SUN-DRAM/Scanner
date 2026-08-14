"""create users, organisations, memberships, otp_codes, sessions tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.create_table(
        "organisations",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("plan_code", sa.String(length=20), nullable=False, server_default="free"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "memberships",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("org_id", "user_id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.org_id"], name="fk_memberships_org_id"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name="fk_memberships_user_id"),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.user_id"], name="fk_memberships_invited_by"
        ),
    )
    op.create_index("memberships_user_id_idx", "memberships", ["user_id"])

    op.create_table(
        "otp_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "otp_codes_email_purpose_created_idx",
        "otp_codes",
        ["email", "purpose", sa.text("created_at DESC")],
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name="fk_sessions_user_id"),
    )
    op.create_index("sessions_user_id_idx", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("sessions_user_id_idx", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("otp_codes_email_purpose_created_idx", table_name="otp_codes")
    op.drop_table("otp_codes")

    op.drop_index("memberships_user_id_idx", table_name="memberships")
    op.drop_table("memberships")

    op.drop_table("organisations")

    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_table("users")
