"""SQLAlchemy 2.0 tables — schema exactly as contract §11."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ScanRecord(Base):
    __tablename__ = "scans"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_slug: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, server_default="443")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    overall_grade: Mapped[str | None] = mapped_column(String(2))
    overall_score: Mapped[int | None] = mapped_column(Integer)
    headline: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("scans_hostname_created_idx", "hostname", text("created_at DESC")),
        Index("scans_status_idx", "status"),
    )


class WaitlistSignupRecord(Base):
    __tablename__ = "waitlist_signups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.scan_id"), nullable=False
    )
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("waitlist_signups_scan_id_idx", "scan_id"),
        Index("waitlist_signups_created_at_idx", text("created_at DESC")),
    )


class UserRecord(Base):
    """Contract §6.6 `User`. Email OTP only (§7.6) — no password column
    exists anywhere in this schema. `email` is always stored lowercased and
    trimmed (app/otp.py normalizes before every write and lookup), so the
    plain unique constraint below is enough without a case-insensitive
    column type."""

    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganisationRecord(Base):
    """Contract §6.7 `Organisation`."""

    __tablename__ = "organisations"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    plan_code: Mapped[str] = mapped_column(String(20), nullable=False, server_default="free")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MembershipRecord(Base):
    """Contract §6.8 `Membership`. Composite primary key — a user has at
    most one role in a given org, and "is this user in this org" is the
    only lookup shape §Step 2/§Step 3 ever need."""

    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.org_id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("memberships_user_id_idx", "user_id"),)


class OtpCodeRecord(Base):
    """Not part of the JSON contract — an internal table backing §7.6's OTP
    rules. The code itself is never stored, only its hash (same discipline
    as `client_ip_hash`): `code_hash = sha256(email + ':' + code)`, salted
    with the email so the same 6-digit code for two different addresses
    never collides in this column."""

    __tablename__ = "otp_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("otp_codes_email_purpose_created_idx", "email", "purpose", text("created_at DESC")),
    )


class SessionRecord(Base):
    """Not part of the JSON contract — backs the `sd_session` cookie (§7.6).
    The cookie's value is `{session_id}.{hmac_sha256(session_id, SESSION_SECRET)}`
    (app/sessions.py) — the signature is verified against `SESSION_SECRET`
    before this row is even looked up, so a forged or tampered session_id is
    rejected without a database round trip, and this row itself never has to
    store a secret (a leaked row is bookkeeping, not a working credential).
    `expires_at` is pushed forward on every authenticated request that
    succeeds — the sliding renewal §7.6 describes — rather than a fixed
    value set once at login."""

    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("sessions_user_id_idx", "user_id"),)


class DailyStatsRecord(Base):
    """One row per UTC day, upserted in place (`app.stats.increment_daily_stat`)
    rather than derived from `scans` — `share_link_opens` has no other table
    to derive from, so every counter lives here for one consistent shape."""

    __tablename__ = "daily_stats"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    scans_started: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    scans_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    scans_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    share_link_opens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    waitlist_signups: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
