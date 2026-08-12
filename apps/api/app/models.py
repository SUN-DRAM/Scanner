"""SQLAlchemy 2.0 tables — schema exactly as contract §11."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
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
