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
    UniqueConstraint,
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
    # Phase 2 Step 3. Null for every public, unauthenticated scan (Phase 1's
    # only kind) — set only when app/monitors.py or the Step 4 scheduler
    # enqueues a scan on behalf of a MonitoredHostname, so that scan's
    # completion can update that monitor's denormalised last_grade/
    # last_score/last_scanned_at (see app/monitors.py's
    # update_monitor_after_scan, called from scanner/orchestrator.py). Not
    # part of the JSON contract's Scan shape (§6.1) — an internal linkage
    # column only.
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_hostnames.monitor_id")
    )

    __table_args__ = (
        Index("scans_hostname_created_idx", "hostname", text("created_at DESC")),
        Index("scans_status_idx", "status"),
        Index("scans_monitor_id_idx", "monitor_id", text("created_at DESC")),
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
    # Phase 2 Step 5 (contract v2.0's own log flagged these as this step's
    # concern to add, not invented ahead of it). IANA zone name, "HH:MM"
    # 24-hour local times, and DigestMode (§5) — every org gets a working
    # default the day it's created, before anyone visits Step 7's settings
    # page to change one.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Kolkata"
    )
    quiet_hours_start: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="21:00"
    )
    quiet_hours_end: Mapped[str] = mapped_column(String(5), nullable=False, server_default="08:00")
    # "Default: digest on free, immediate on paid" (§Step 5) — every org is
    # created on the free plan (app/otp.py), so "digest" is the one default
    # this column ever needs until Step 6's billing can change plan_code.
    digest_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="digest")
    # Not specified by the phase prompt ("a chosen hour" implies the org
    # picks it — Step 7's settings page): defaults to 09:00 local.
    digest_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="9")
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


class MonitoredHostnameRecord(Base):
    """Contract §6.9 `MonitoredHostname`. Reuses §7.2 normalisation and §10
    safety guard unchanged before a row is ever created — app/monitors.py,
    never a parallel validation path."""

    __tablename__ = "monitored_hostnames"

    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.org_id"), nullable=False
    )
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, server_default="443")
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    label: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.scan_id")
    )
    last_grade: Mapped[str | None] = mapped_column(String(2))
    last_score: Mapped[int | None] = mapped_column(Integer)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Not part of the JSON contract: §6.9's `days_until_expiry` is a
    # countdown that moves every day without a new scan, so it is derived at
    # serialisation time (app/monitors.py) from this timestamp rather than
    # stored as a stale integer. Set alongside last_grade/last_score/
    # last_scanned_at whenever a linked scan completes.
    cert_not_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 2 Step 4. Not part of the JSON contract. Incremented by
    # app/monitors.py's record_scan_failure on every failed scan tied to
    # this monitor (scheduled or manual), reset to 0 on the next success —
    # drives the retry-backoff schedule and the scan_failure alert firing
    # threshold (§Step 4).
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Not specified by the phase prompt: "hostname already monitored in
        # this org" (§7.4 DUPLICATE_HOSTNAME) is scoped to (org_id, hostname,
        # port) together, not hostname alone — example.com:443 and
        # example.com:8443 are different monitoring targets, matching how
        # §10's own port allowlist treats them as distinct scan targets.
        UniqueConstraint(
            "org_id", "hostname", "port", name="uq_monitored_hostnames_org_hostname_port"
        ),
        Index("monitored_hostnames_org_id_idx", "org_id"),
        Index("monitored_hostnames_state_idx", "state"),
    )


class AlertEventRecord(Base):
    """Contract §6.11 `AlertEvent`. Phase 2 Step 4 was the first writer —
    app/monitors.py's scan_failure firing, once a monitor's retries are
    exhausted. Step 5 (app/alerts.py) adds the other four `AlertType`s,
    dedup-on-`sent`/`pending`-state, quiet hours, digest batching, and
    actual delivery on top of this same table, not a parallel one. No
    Pydantic schema exists yet (schemas.py/contract.ts) because nothing
    serialises this to JSON until Step 7's `/app/alerts` dashboard reads
    it — adding one now, ahead of that, is exactly the "generated but not
    yet defined" drift CONTRACT.md rule 9 exists to prevent."""

    __tablename__ = "alert_events"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.org_id"), nullable=False
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_hostnames.monitor_id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipients: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Phase 2 Step 5, not part of the JSON contract. "Retry 3x with backoff"
    # (§Step 5) reuses the delivery cron's own 5-minute cadence as the
    # backoff, the same pattern Step 4's scan retries already established —
    # incremented on each failed send attempt, `state` becomes `failed`
    # once this reaches 3 rather than retrying forever.
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("alert_events_dedupe_key_idx", "dedupe_key"),
        Index("alert_events_org_id_idx", "org_id"),
        Index("alert_events_state_scheduled_for_idx", "state", "scheduled_for"),
    )


class AlertRecipientRecord(Base):
    """Contract §6.10 `AlertRecipient`. No management endpoint exists yet
    (Step 7's `/app/alerts` settings page) — app/alerts.py resolves and
    delivers against whatever rows exist here, falling back to every
    `owner`/`admin` membership's email when an org has added none, so
    alerts are never silently dropped just because nobody has visited that
    settings page yet."""

    __tablename__ = "alert_recipients"

    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.org_id"), nullable=False
    )
    # Null = org-wide (every monitor); non-null scopes to one monitor (§6.10).
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_hostnames.monitor_id")
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Not part of the JSON contract's §6.10 shape (which only has
    # `verified`) — a distinct concept: `verified` means "confirmed this
    # address is real", `unsubscribed` means "opted out of alerts". A
    # recipient can be both verified and unsubscribed.
    unsubscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("alert_recipients_org_id_idx", "org_id"),)


class SubscriptionRecord(Base):
    """Contract §6.12 `Subscription`. First written by Step 6 (§7.11) — v2.0
    only reserved the shape. One row per org that has ever completed a
    checkout (`org_id` unique): a webhook upserts this in place rather than
    inserting a second row, so a cancel-then-resubscribe cycle still has
    exactly one `Subscription` per org, matching the contract shape (a
    single object, not a list — there is no "list subscriptions"
    endpoint). A free org that has never checked out has no row at all;
    `GET /billing/subscription` returns `null`, not `404`."""

    __tablename__ = "subscriptions"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.org_id"), nullable=False, unique=True
    )
    plan_code: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="trialing")
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("subscriptions_org_id_idx", "org_id"),)


class InvoiceRecord(Base):
    """Contract §6.13 `Invoice`. One row per successful charge (a
    `subscription.charged`/`invoice.paid` webhook event, §7.11) — Phase 2
    has no refund/void flow, so a row is never edited after creation except
    by a future phase. `number` follows the contract's own example format
    (`INV-{year}-{6-digit sequence}`), generated in `app/billing/service.py`
    with a unique-constraint retry, same mechanics as `scans.public_slug`'s
    collision handling."""

    __tablename__ = "invoices"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.org_id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="paid")
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    # India tax fields (§6.13) — captured at checkout time (§7.11's
    # BillingCheckoutRequest), carried through the provider's own
    # metadata/notes, and copied here from the webhook event that produced
    # this invoice. Both null when the customer supplied neither.
    gstin: Mapped[str | None] = mapped_column(String(20))
    place_of_supply: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (Index("invoices_org_id_idx", "org_id", text("issued_at DESC")),)


class BillingEventRecord(Base):
    """Not part of the JSON contract. Idempotency ledger for provider
    webhooks (§Step 6: "Handle them idempotently — providers retry, and
    double-applying a plan change is a real bug. Store the provider event id
    and skip duplicates.") — one row per `(provider, event_id)` ever
    successfully processed, inserted before any `subscriptions`/`invoices`/
    `organisations` row is touched; a retried delivery hits the unique
    constraint and is recognised as a duplicate, same collision-as-signal
    pattern `app/monitors.py`'s `DUPLICATE_HOSTNAME` handling already uses."""

    __tablename__ = "billing_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event_id"),
    )


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
