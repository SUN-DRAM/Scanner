"""The daily internal digest (contract §7.13): one plain-text email to
`ADMIN_DIGEST_EMAIL` each morning so a 3am problem is known by 8am rather
than when a customer reports it.

Fired by `app/worker.py`'s `admin_digest_tick` cron at 02:30 UTC
(08:00 Asia/Kolkata). Empty `ADMIN_DIGEST_EMAIL` → nothing is computed or
sent. Delivery reuses the Phase 2 `get_email_sender()`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.ops import _OVERDUE_1H_AFTER, _STUCK_GRACE_SECONDS
from app.config import get_settings
from app.enums import AlertState, MonitorState, ScanStatus, SubscriptionState
from app.models import (
    AlertEventRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    ScanRecord,
    SubscriptionRecord,
)
from app.notify.email import EmailSender

logger = logging.getLogger("app.admin.digest")

_SUBJECT = "SUN-DRAM daily digest"


async def _count(session: AsyncSession, stmt: Select[tuple[int]]) -> int:
    return int((await session.execute(stmt)).scalar_one())


async def collect_digest_stats(session: AsyncSession, now: datetime) -> dict[str, int]:
    since = now - timedelta(hours=24)

    new_signups = await _count(
        session,
        select(func.count())
        .select_from(OrganisationRecord)
        .where(OrganisationRecord.created_at >= since),
    )
    hostnames_added = await _count(
        session,
        select(func.count())
        .select_from(MonitoredHostnameRecord)
        .where(MonitoredHostnameRecord.created_at >= since),
    )
    # Activation = the org added its *first* hostname in the last 24h.
    first_monitor = (
        select(
            MonitoredHostnameRecord.org_id.label("org_id"),
            func.min(MonitoredHostnameRecord.created_at).label("first_at"),
        )
        .group_by(MonitoredHostnameRecord.org_id)
        .subquery()
    )
    activations = await _count(
        session,
        select(func.count()).select_from(first_monitor).where(first_monitor.c.first_at >= since),
    )
    alerts_sent = await _count(
        session,
        select(func.count())
        .select_from(AlertEventRecord)
        .where(
            AlertEventRecord.state == AlertState.SENT.value,
            AlertEventRecord.sent_at.is_not(None),
            AlertEventRecord.sent_at >= since,
        ),
    )
    alerts_failed = await _count(
        session,
        select(func.count())
        .select_from(AlertEventRecord)
        .where(
            AlertEventRecord.state == AlertState.FAILED.value,
            AlertEventRecord.created_at >= since,
        ),
    )
    stuck_cutoff = now - timedelta(
        seconds=get_settings().scan_timeout_seconds + _STUCK_GRACE_SECONDS
    )
    scans_stuck = await _count(
        session,
        select(func.count())
        .select_from(ScanRecord)
        .where(
            ScanRecord.status.in_([ScanStatus.QUEUED.value, ScanStatus.RUNNING.value]),
            ScanRecord.created_at < stuck_cutoff,
        ),
    )
    monitors_overdue = await _count(
        session,
        select(func.count())
        .select_from(MonitoredHostnameRecord)
        .where(
            MonitoredHostnameRecord.state == MonitorState.ACTIVE.value,
            MonitoredHostnameRecord.next_scan_at.is_not(None),
            MonitoredHostnameRecord.next_scan_at <= now - _OVERDUE_1H_AFTER,
        ),
    )
    new_paid = await _count(
        session,
        select(func.count())
        .select_from(SubscriptionRecord)
        .where(
            SubscriptionRecord.state == SubscriptionState.ACTIVE.value,
            SubscriptionRecord.created_at >= since,
        ),
    )

    return {
        "new_signups": new_signups,
        "activations": activations,
        "hostnames_added": hostnames_added,
        "alerts_sent": alerts_sent,
        "alerts_failed": alerts_failed,
        "scans_stuck": scans_stuck,
        "monitors_overdue": monitors_overdue,
        "new_paid_conversions": new_paid,
    }


def render_digest(stats: dict[str, int], now: datetime) -> str:
    generated = now.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"SUN-DRAM Scanner — last 24 hours (as of {generated})",
        "",
        f"New signups             {stats['new_signups']}",
        f"Activations             {stats['activations']}",
        f"Hostnames added         {stats['hostnames_added']}",
        f"Alerts sent             {stats['alerts_sent']}",
        f"Alerts failed           {stats['alerts_failed']}",
        f"Scans stuck             {stats['scans_stuck']}",
        f"Monitors overdue >1h    {stats['monitors_overdue']}",
        f"New paid conversions    {stats['new_paid_conversions']}",
    ]
    if stats["alerts_failed"] or stats["scans_stuck"] or stats["monitors_overdue"]:
        lines += ["", "Something above is non-zero that shouldn't be — check /admin/health."]
    return "\n".join(lines) + "\n"


async def send_admin_digest(session: AsyncSession, email_sender: EmailSender) -> bool:
    """Returns True if an email was handed to the sender, False if
    `ADMIN_DIGEST_EMAIL` is unset (nothing to do)."""
    recipient = get_settings().admin_digest_email
    if not recipient:
        return False
    now = datetime.now(UTC)
    stats = await collect_digest_stats(session, now)
    await email_sender.send(to=recipient, subject=_SUBJECT, text=render_digest(stats, now))
    logger.info("admin_digest_sent", extra={"to": recipient})
    return True
