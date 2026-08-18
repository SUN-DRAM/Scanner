"""Phase 2 Step 5: the alert engine.

`evaluate_and_fire_alerts` runs after every completed monitor-linked scan
(called from `scanner/orchestrator.py`, before `app.monitors.
update_monitor_after_scan` overwrites the monitor's previous grade/cert
state) and records zero or more `AlertEvent` rows for the four trigger
types this step owns — `cert_expiry`, `domain_expiry`, `grade_regression`,
`new_critical_finding`. `scan_failure` is Step 4's own
(`app.monitors._fire_scan_failure_alert`), reusing this same table.

`deliver_pending_alerts`, run every 5 minutes by a cron job
(`app/worker.py`), resolves recipients, batches what quiet hours/digest
mode say should be batched, and sends through `app.notify.email`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import AlertState, AlertType, DigestMode, Grade, PlanCode, ScanStatus, Severity
from app.models import (
    AlertEventRecord,
    AlertRecipientRecord,
    MembershipRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    ScanRecord,
    UserRecord,
)
from app.notify.email import EmailSender, EmailSendError
from app.plans import PlanDefinition, get_plan
from app.schemas import Scan

logger = logging.getLogger("app.alerts")

# §Step 5: "Retry 3x with backoff" — reuses the delivery cron's own
# 5-minute cadence as the backoff, the same pattern Step 4's scan retries
# established (no separate retry job or sleep-based backoff in-process).
MAX_SEND_ATTEMPTS = 3

# §Step 5: "cert_expiry at ≤3 days and scan_failure ignore quiet hours" —
# the only two cases that bypass both quiet hours and digest batching.
_URGENT_CERT_EXPIRY_MAX_DAYS = 3

_DOMAIN_ALERT_LEAD_DAYS: tuple[int, ...] = (45, 14)  # §Step 5, fixed — not plan-dependent

_GRADE_BAND_ORDER: tuple[Grade, ...] = (
    Grade.A_PLUS,
    Grade.A,
    Grade.B,
    Grade.C,
    Grade.D,
    Grade.E,
    Grade.F,
)


class _Candidate:
    __slots__ = ("type", "threshold", "severity", "urgent", "subject", "body")

    def __init__(
        self,
        *,
        type: AlertType,
        threshold: str,
        severity: Severity,
        urgent: bool,
        subject: str,
        body: str,
    ) -> None:
        self.type = type
        self.threshold = threshold
        self.severity = severity
        self.urgent = urgent
        self.subject = subject
        self.body = body


def _cert_expiry_severity(lead_day: int) -> Severity:
    # Mirrors findings.py's own certificate.py bands (§8 CERT_EXPIRING_*),
    # extended to cover the paid plans' 60-day lead (findings.py never
    # needed a band that far out, since it only fires from a live scan's
    # actual day count, not a plan's configured lead list).
    if lead_day <= 3:
        return Severity.CRITICAL
    if lead_day <= 14:
        return Severity.HIGH
    if lead_day <= 30:
        return Severity.MEDIUM
    return Severity.LOW


def _cert_expiry_candidates(
    monitor: MonitoredHostnameRecord,
    plan: PlanDefinition,
    scan: Scan,
    previous_days: int | None,
) -> list[_Candidate]:
    cert = scan.modules.certificate.data if scan.modules.certificate else None
    if cert is None or cert.days_until_expiry is None:
        return []
    current_days = cert.days_until_expiry

    candidates: list[_Candidate] = []
    for lead_day in plan.alert_lead_days:
        crossed_now = current_days <= lead_day
        crossed_before = previous_days is not None and previous_days <= lead_day
        if crossed_now and not crossed_before:
            candidates.append(
                _Candidate(
                    type=AlertType.CERT_EXPIRY,
                    threshold=str(lead_day),
                    severity=_cert_expiry_severity(lead_day),
                    urgent=lead_day <= _URGENT_CERT_EXPIRY_MAX_DAYS,
                    subject=f"{monitor.hostname} — certificate expires in {current_days} days",
                    body=(
                        f"The certificate for {monitor.hostname} expires in {current_days} "
                        f"days, on {cert.not_after.date().isoformat()}."
                    ),
                )
            )
    return candidates


def _domain_expiry_candidates(
    monitor: MonitoredHostnameRecord, scan: Scan, previous_days: int | None
) -> list[_Candidate]:
    dns_data = scan.modules.dns.data if scan.modules.dns else None
    if dns_data is None or dns_data.days_until_domain_expiry is None:
        return []
    current_days = dns_data.days_until_domain_expiry

    candidates: list[_Candidate] = []
    for lead_day in _DOMAIN_ALERT_LEAD_DAYS:
        crossed_now = current_days <= lead_day
        crossed_before = previous_days is not None and previous_days <= lead_day
        if crossed_now and not crossed_before:
            candidates.append(
                _Candidate(
                    type=AlertType.DOMAIN_EXPIRY,
                    threshold=str(lead_day),
                    # findings.py's DOMAIN_EXPIRING_* codes are both HIGH,
                    # never CRITICAL — a WHOIS-derived claim must not read
                    # as more certain than a live TLS handshake (§8 v1.4).
                    severity=Severity.HIGH,
                    urgent=False,
                    subject=(
                        f"{monitor.hostname} — domain registration expires in {current_days} days"
                    ),
                    body=(
                        f"The registry record for {monitor.hostname} says it expires in "
                        f"{current_days} days. Confirm with your registrar before treating "
                        "this as certain — registry records are sometimes stale."
                    ),
                )
            )
    return candidates


def _grade_regression_candidate(
    monitor: MonitoredHostnameRecord, scan: Scan, previous_grade: str | None
) -> _Candidate | None:
    if previous_grade is None or scan.overall_grade is None:
        return None
    try:
        previous_index = _GRADE_BAND_ORDER.index(Grade(previous_grade))
        current_index = _GRADE_BAND_ORDER.index(scan.overall_grade)
    except ValueError:
        return None
    if current_index <= previous_index:  # same band or improved
        return None
    return _Candidate(
        type=AlertType.GRADE_REGRESSION,
        threshold=scan.overall_grade.value,
        severity=Severity.HIGH,
        urgent=False,
        subject=f"{monitor.hostname} — grade dropped to {scan.overall_grade.value}",
        body=(
            f"{monitor.hostname}'s grade dropped from {previous_grade} to "
            f"{scan.overall_grade.value}. {scan.headline or ''}".strip()
        ),
    )


def _critical_or_high_codes(scan: Scan) -> set[str]:
    return {
        finding.code
        for finding in scan.findings
        if finding.severity in (Severity.CRITICAL, Severity.HIGH)
    }


def _new_critical_finding_candidates(
    monitor: MonitoredHostnameRecord, scan: Scan, previous_scan: Scan | None
) -> list[_Candidate]:
    current_codes = _critical_or_high_codes(scan)
    previous_codes = _critical_or_high_codes(previous_scan) if previous_scan is not None else set()
    new_codes = current_codes - previous_codes

    matching = [finding for finding in scan.findings if finding.code in new_codes]
    return [
        _Candidate(
            type=AlertType.NEW_CRITICAL_FINDING,
            threshold=finding.code,
            severity=finding.severity,
            urgent=False,
            subject=f"{monitor.hostname} — new finding: {finding.title}",
            body=f"{finding.description} {finding.remediation}".strip(),
        )
        for finding in matching
    ]


async def _fetch_previous_completed_scan(
    session: AsyncSession, monitor_id: uuid.UUID, exclude_scan_id: uuid.UUID
) -> Scan | None:
    stmt = (
        select(ScanRecord)
        .where(
            ScanRecord.monitor_id == monitor_id,
            ScanRecord.status == ScanStatus.COMPLETED.value,
            ScanRecord.scan_id != exclude_scan_id,
        )
        .order_by(ScanRecord.created_at.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None or record.result is None:
        return None
    return Scan.model_validate(record.result)


def _parse_hhmm(value: str) -> time:
    hour_str, _, minute_str = value.partition(":")
    return time(int(hour_str), int(minute_str))


def _in_quiet_hours(local_time: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= local_time < end
    return local_time >= start or local_time < end  # window wraps midnight


def _defer_past_quiet_hours(org: OrganisationRecord, now: datetime) -> datetime:
    tz = ZoneInfo(org.timezone)
    local_now = now.astimezone(tz)
    start = _parse_hhmm(org.quiet_hours_start)
    end = _parse_hhmm(org.quiet_hours_end)
    if not _in_quiet_hours(local_now.time(), start, end):
        return now

    candidate_local = local_now.replace(
        hour=end.hour, minute=end.minute, second=0, microsecond=0
    )
    if candidate_local <= local_now:
        candidate_local += timedelta(days=1)
    return candidate_local.astimezone(UTC)


def _next_digest_slot(org: OrganisationRecord, after: datetime) -> datetime:
    tz = ZoneInfo(org.timezone)
    local_after = after.astimezone(tz)
    candidate_local = local_after.replace(
        hour=org.digest_hour, minute=0, second=0, microsecond=0
    )
    if candidate_local <= local_after:
        candidate_local += timedelta(days=1)
    return candidate_local.astimezone(UTC)


def compute_scheduled_for(org: OrganisationRecord, *, urgent: bool, now: datetime) -> datetime:
    """§Step 5's quiet-hours and digest-mode rules, both expressed as "when
    should this send" — a non-urgent alert first defers past quiet hours,
    then (if the org digests) defers again to the next digest slot. An
    urgent alert (cert_expiry ≤3 days, or scan_failure via app/monitors.py)
    always schedules immediately, ignoring both."""
    if urgent:
        return now
    deferred = _defer_past_quiet_hours(org, now)
    if org.digest_mode == DigestMode.DIGEST.value:
        return _next_digest_slot(org, deferred)
    return deferred


async def _already_fired(session: AsyncSession, dedupe_key: str) -> bool:
    stmt = select(AlertEventRecord.alert_id).where(
        AlertEventRecord.dedupe_key == dedupe_key,
        AlertEventRecord.state.in_((AlertState.PENDING.value, AlertState.SENT.value)),
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _fire_candidate(
    session: AsyncSession,
    org: OrganisationRecord,
    monitor: MonitoredHostnameRecord,
    candidate: _Candidate,
    now: datetime,
) -> None:
    dedupe_key = f"{monitor.monitor_id}:{candidate.type.value}:{candidate.threshold}"
    # §Step 5: "A key already in sent state never sends again." Checked
    # against `pending` too, not just `sent` — otherwise two scans landing
    # in the same delivery window could each create a duplicate before
    # either is actually sent.
    if await _already_fired(session, dedupe_key):
        return

    session.add(
        AlertEventRecord(
            alert_id=uuid.uuid4(),
            org_id=org.org_id,
            monitor_id=monitor.monitor_id,
            type=candidate.type.value,
            state=AlertState.PENDING.value,
            severity=candidate.severity.value,
            subject=candidate.subject,
            dedupe_key=dedupe_key,
            scheduled_for=compute_scheduled_for(org, urgent=candidate.urgent, now=now),
            sent_at=None,
            recipients=[],
            payload={"hostname": monitor.hostname, "body": candidate.body},
        )
    )


async def evaluate_and_fire_alerts(
    session: AsyncSession,
    org: OrganisationRecord,
    monitor: MonitoredHostnameRecord,
    scan: Scan,
) -> None:
    """Called by `scanner/orchestrator.py` for a completed scan tied to a
    monitor, before `app.monitors.update_monitor_after_scan` overwrites
    `monitor.last_grade`/`monitor.cert_not_after` — both are read here as
    "the previous scan's values" first."""
    if scan.status != ScanStatus.COMPLETED:
        return

    now = datetime.now(UTC)
    plan = get_plan(PlanCode(org.plan_code))

    previous_cert_days: int | None = None
    if monitor.cert_not_after is not None:
        previous_cert_days = (monitor.cert_not_after.replace(tzinfo=UTC) - scan.created_at).days
    previous_grade = monitor.last_grade

    previous_scan = await _fetch_previous_completed_scan(
        session, monitor.monitor_id, uuid.UUID(scan.scan_id)
    )
    previous_domain_days: int | None = None
    if previous_scan is not None and previous_scan.modules.dns is not None:
        dns_data = previous_scan.modules.dns.data
        if dns_data is not None:
            previous_domain_days = dns_data.days_until_domain_expiry

    candidates: list[_Candidate] = []
    candidates.extend(_cert_expiry_candidates(monitor, plan, scan, previous_cert_days))
    candidates.extend(_domain_expiry_candidates(monitor, scan, previous_domain_days))
    grade_candidate = _grade_regression_candidate(monitor, scan, previous_grade)
    if grade_candidate is not None:
        candidates.append(grade_candidate)
    candidates.extend(_new_critical_finding_candidates(monitor, scan, previous_scan))

    if not candidates:
        return
    for candidate in candidates:
        await _fire_candidate(session, org, monitor, candidate, now)
    await session.commit()


# --- delivery (arq cron, every 5 minutes — app/worker.py) ---


async def _resolve_recipients(
    session: AsyncSession, org: OrganisationRecord, monitor_id: uuid.UUID
) -> list[tuple[str, uuid.UUID | None]]:
    """Org-wide (`monitor_id IS NULL`) plus this-monitor recipients. Falls
    back to every `owner`/`admin` membership's email only when the org has
    configured *no* `AlertRecipient` rows at all (Step 7 hasn't shipped the
    settings page that would let them yet) — an `AlertRecipient` id is
    `None` for those, since they have nothing to unsubscribe from.

    Deliberately two queries, not one filtered query with a fallback on an
    empty result: if every configured recipient has unsubscribed, that
    must suppress the alert, not silently re-route it to the org's owners
    through the fallback — "no rows configured" and "every row opted out"
    are different states and must not collapse into the same behaviour.
    """
    base_filter = (
        AlertRecipientRecord.org_id == org.org_id,
        or_(
            AlertRecipientRecord.monitor_id.is_(None),
            AlertRecipientRecord.monitor_id == monitor_id,
        ),
    )
    any_configured_stmt = select(AlertRecipientRecord.recipient_id).where(*base_filter).limit(1)
    if (await session.execute(any_configured_stmt)).scalar_one_or_none() is None:
        fallback_stmt = (
            select(UserRecord.email)
            .join(MembershipRecord, MembershipRecord.user_id == UserRecord.user_id)
            .where(
                MembershipRecord.org_id == org.org_id,
                MembershipRecord.role.in_(("owner", "admin")),
            )
        )
        emails = (await session.execute(fallback_stmt)).scalars().all()
        return [(email, None) for email in emails]

    subscribed_stmt = select(AlertRecipientRecord).where(
        *base_filter, AlertRecipientRecord.unsubscribed.is_(False)
    )
    rows = (await session.execute(subscribed_stmt)).scalars().all()
    return [(row.email, row.recipient_id) for row in rows]


def _render(events: list[AlertEventRecord]) -> tuple[str, list[str]]:
    """Plain, text-first, sentence case, no marketing chrome (§Step 5). A
    single event keeps its own subject; a digest batch gets a summary
    subject and one line per alert so it's actionable from a phone
    notification without opening the mail."""
    if len(events) == 1:
        event = events[0]
        body = str(event.payload.get("body", event.subject))
        return event.subject, [body]

    hostnames = sorted({str(event.payload.get("hostname", "")) for event in events})
    subject = f"{len(events)} alerts across {len(hostnames)} hostname(s)"
    lines = [event.subject for event in events]
    return subject, lines


async def _send_to_recipients(
    email_sender: EmailSender,
    recipients: list[tuple[str, uuid.UUID | None]],
    subject: str,
    body_lines: list[str],
) -> bool:
    settings = get_settings()
    base_lines = list(body_lines)
    try:
        for email, recipient_id in recipients:
            lines = list(base_lines)
            if recipient_id is not None:
                unsubscribe_url = (
                    f"{settings.public_base_url}/api/v1/alerts/unsubscribe/{recipient_id}"
                )
                lines.append(f"\nUnsubscribe: {unsubscribe_url}")
            await email_sender.send(to=email, subject=subject, text="\n".join(lines))
        return True
    except EmailSendError:
        return False


async def deliver_pending_alerts(session: AsyncSession, email_sender: EmailSender) -> int:
    """One delivery tick: sends everything `pending` and due, batching by
    (org, monitor) so a digest becomes one email, not one per alert.
    Returns how many `AlertEvent`s were delivered, for logging."""
    now = datetime.now(UTC)
    stmt = (
        select(AlertEventRecord)
        .where(
            AlertEventRecord.state == AlertState.PENDING.value,
            AlertEventRecord.scheduled_for <= now,
        )
        .order_by(AlertEventRecord.org_id, AlertEventRecord.monitor_id)
    )
    due = (await session.execute(stmt)).scalars().all()
    if not due:
        return 0

    batches: dict[tuple[uuid.UUID, uuid.UUID], list[AlertEventRecord]] = {}
    for event in due:
        batches.setdefault((event.org_id, event.monitor_id), []).append(event)

    delivered = 0
    orgs_cache: dict[uuid.UUID, OrganisationRecord | None] = {}
    for (org_id, monitor_id), events in batches.items():
        if org_id not in orgs_cache:
            orgs_cache[org_id] = await session.get(OrganisationRecord, org_id)
        org = orgs_cache[org_id]
        if org is None:
            continue

        recipients = await _resolve_recipients(session, org, monitor_id)
        if not recipients:
            for event in events:
                event.state = AlertState.SUPPRESSED.value
            continue

        subject, body_lines = _render(events)
        success = await _send_to_recipients(email_sender, recipients, subject, body_lines)
        if success:
            for event in events:
                event.state = AlertState.SENT.value
                event.sent_at = now
                event.recipients = [email for email, _ in recipients]
            delivered += len(events)
        else:
            for event in events:
                event.send_attempts += 1
                if event.send_attempts >= MAX_SEND_ATTEMPTS:
                    event.state = AlertState.FAILED.value
                    # §Step 5: "alert us, not the customer, on repeated send
                    # failure" — Sentry (already wired, Gate C) captures
                    # ERROR-level logs, so this is the alert.
                    logger.error(
                        "alert_delivery_permanently_failed",
                        extra={"alert_id": str(event.alert_id), "org_id": str(org_id)},
                    )

    await session.commit()
    return delivered


async def unsubscribe_recipient(
    session: AsyncSession, recipient_id: uuid.UUID
) -> AlertRecipientRecord | None:
    recipient = await session.get(AlertRecipientRecord, recipient_id)
    if recipient is None:
        return None
    recipient.unsubscribed = True
    await session.commit()
    return recipient


async def get_or_create_recipient(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    monitor_id: uuid.UUID | None,
    email: str,
) -> tuple[AlertRecipientRecord, bool]:
    """Idempotent on `(org_id, monitor_id, email)` (§7.12) — the same
    convention `POST /orgs/current/members` already established for
    re-inviting an existing member. The one place an `AlertRecipient` row is
    created — shared by `routers/alerts.py`'s `POST /alerts/recipients` and
    `app/commands/migrate_waitlist.py` (Step 8), so re-running the waitlist
    migration never produces a duplicate recipient. Returns `(record,
    created)`; `created` is `False` when an existing row was returned
    unchanged."""
    normalized_email = email.strip().lower()
    existing_stmt = select(AlertRecipientRecord).where(
        AlertRecipientRecord.org_id == org_id,
        AlertRecipientRecord.monitor_id == monitor_id,
        AlertRecipientRecord.email == normalized_email,
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return existing, False

    record = AlertRecipientRecord(
        recipient_id=uuid.uuid4(),
        org_id=org_id,
        monitor_id=monitor_id,
        email=normalized_email,
        # True at creation, not pending a verification flow — §7.12: no such
        # flow exists anywhere in Phase 2, and delivery never gates on this
        # flag, only on `unsubscribed`.
        verified=True,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record, True
