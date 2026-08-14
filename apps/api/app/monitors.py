"""Monitored-hostname business logic (contract §6.9/§7.8): creation (reusing
§7.2 normalisation and the §10 safety guard exactly as `routers/scans.py`'s
`POST /api/v1/scans` does), quota accounting against `app/plans.py`, manual
re-scans, and updating a monitor's denormalised fields once a scan tied to
it completes.

The one place a `monitored_hostnames` row is created, mirroring how
`app/otp.py` is the one place a `users` row is created from a login.
"""

from __future__ import annotations

import contextlib
import hashlib
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AlertState, AlertType, Grade, MonitorState, PlanCode, ScanStatus, Severity
from app.errors import ApiException, ErrorCode
from app.models import AlertEventRecord, MonitoredHostnameRecord, OrganisationRecord, ScanRecord
from app.plans import get_plan, next_purchasable_plan
from app.safety import (
    HostnameResolutionError,
    NormalizedHost,
    normalize_hostname,
    resolve_and_validate,
    validate_port,
)

# States that occupy a quota slot. `quota_blocked` is deliberately excluded —
# it already *is* the overflow a plan's limit produced, so counting it too
# would make a monitor block against the very quota it's blocked by (§7.8).
QUOTA_COUNTED_STATES: frozenset[str] = frozenset(
    {
        MonitorState.ACTIVE.value,
        MonitorState.PAUSED.value,
        MonitorState.VERIFICATION_PENDING.value,
    }
)


async def count_quota_monitors(session: AsyncSession, org_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(MonitoredHostnameRecord)
        .where(
            MonitoredHostnameRecord.org_id == org_id,
            MonitoredHostnameRecord.state.in_(QUOTA_COUNTED_STATES),
        )
    )
    return (await session.execute(stmt)).scalar_one()


def _quota_exceeded_error(current: int, org: OrganisationRecord) -> ApiException:
    plan = get_plan(PlanCode(org.plan_code))
    upgrade_to = next_purchasable_plan(PlanCode(org.plan_code))
    return ApiException(
        ErrorCode.QUOTA_EXCEEDED,
        "You've reached your plan's monitored-hostname limit.",
        {
            "current": current,
            "limit": plan.hostname_limit,
            "plan_code": org.plan_code,
            "upgrade_to": upgrade_to.value if upgrade_to else None,
        },
    )


async def find_duplicate(
    session: AsyncSession, org_id: uuid.UUID, hostname: str, port: int
) -> MonitoredHostnameRecord | None:
    stmt = select(MonitoredHostnameRecord).where(
        MonitoredHostnameRecord.org_id == org_id,
        MonitoredHostnameRecord.hostname == hostname,
        MonitoredHostnameRecord.port == port,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _duplicate_error(hostname: str, port: int) -> ApiException:
    return ApiException(
        ErrorCode.DUPLICATE_HOSTNAME,
        f"'{hostname}' is already monitored in this organisation.",
        {"hostname": hostname, "port": port},
    )


async def create_monitor(
    session: AsyncSession,
    org: OrganisationRecord,
    *,
    raw_hostname: str,
    requested_port: int | None,
    label: str | None,
    notes: str | None,
    current_quota_count: int,
) -> MonitoredHostnameRecord:
    """Normalises and safety-checks `raw_hostname` (§7.2/§10, identical to
    `routers/scans.py`'s `POST /scans` path), then checks duplicate and
    quota, then creates the row. Raises `ApiException` with
    `INVALID_HOSTNAME`, `BLOCKED_TARGET`, `DUPLICATE_HOSTNAME`, or
    `QUOTA_EXCEEDED` on any failure — the caller (a single create, or the
    bulk loop in `routers/monitors.py`) decides whether that's an HTTP
    error or one rejected bulk row.

    `current_quota_count` is threaded through by the bulk loop so it can
    count rows already accepted earlier in the same batch without
    re-querying the database on every row; a single create passes a
    freshly queried count.
    """
    normalized: NormalizedHost = normalize_hostname(raw_hostname, requested_port)
    validate_port(normalized.port)

    # §10 rules 1+2, synchronous like POST /scans: reject an obvious SSRF
    # target now. A hostname that simply doesn't resolve is NOT rejected —
    # the monitor is still created and a later scan attempt reports it, the
    # same "not an HTTP error" treatment §7.4 gives a public scan.
    with contextlib.suppress(HostnameResolutionError):
        await resolve_and_validate(normalized.hostname)

    existing = await find_duplicate(session, org.org_id, normalized.hostname, normalized.port)
    if existing is not None:
        raise _duplicate_error(normalized.hostname, normalized.port)

    plan = get_plan(PlanCode(org.plan_code))
    if plan.hostname_limit is not None and current_quota_count >= plan.hostname_limit:
        raise _quota_exceeded_error(current_quota_count, org)

    record = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(),
        org_id=org.org_id,
        hostname=normalized.hostname,
        port=normalized.port,
        state=MonitorState.ACTIVE.value,
        label=label,
        notes=notes,
        # Step 4's scheduler owns jittered scheduling; a brand-new monitor
        # is simply due immediately so the next scheduler tick (or a manual
        # rescan) picks it up. Not specified by the phase prompt.
        next_scan_at=datetime.now(UTC),
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _duplicate_error(normalized.hostname, normalized.port) from exc
    await session.refresh(record)
    return record


def compute_days_until_expiry(
    cert_not_after: datetime | None, *, now: datetime | None = None
) -> int | None:
    if cert_not_after is None:
        return None
    reference = now or datetime.now(UTC)
    delta = cert_not_after.replace(tzinfo=UTC) - reference
    return delta.days


async def update_monitor_after_scan(
    session: AsyncSession,
    scan_record: ScanRecord,
    *,
    grade: Grade | None,
    score: int | None,
    cert_not_after: datetime | None,
    scanned_at: datetime,
) -> None:
    """Called by `scanner/orchestrator.py` once a scan tied to a monitor
    (`scan_record.monitor_id` set) reaches `completed` — never on a failed
    scan, so a transient failure doesn't overwrite the last known-good
    grade with nothing. Updates the monitor's denormalised
    `last_scan_id`/`last_grade`/`last_score`/`last_scanned_at`; `§6.9`'s
    `days_until_expiry` is derived from `cert_not_after` at serialisation
    time (`compute_days_until_expiry` above), not stored directly."""
    if scan_record.monitor_id is None:
        return
    monitor = await session.get(MonitoredHostnameRecord, scan_record.monitor_id)
    if monitor is None:
        return
    monitor.last_scan_id = scan_record.scan_id
    monitor.last_grade = grade.value if grade is not None else None
    monitor.last_score = score
    monitor.last_scanned_at = scanned_at
    monitor.cert_not_after = cert_not_after
    monitor.consecutive_failures = 0
    await session.commit()


# --- Step 4: retry backoff and scan_failure alert firing ---

# 5 minutes, 30 minutes, 2 hours (§Step 4) — fixed by the phase prompt, not
# a tunable, unlike the env-configurable rate limits above.
FAILURE_BACKOFF_SECONDS: tuple[int, ...] = (300, 1800, 7200)


async def _fire_scan_failure_alert(session: AsyncSession, monitor: MonitoredHostnameRecord) -> None:
    """Records a `scan_failure` `AlertEvent` (§6.11) once a monitor's
    retries are exhausted. This only *fires* the event — the dedup-on-
    `sent`-state rule, quiet hours, digest batching, and actual delivery
    are Step 5's alert engine, built on top of this same table. The guard
    below only stops a second `pending` row piling up before Step 5's
    engine has processed the first one; once that one reaches `sent`, a
    later failure streak (which requires a success — and consecutive_
    failures resetting to 0 — in between) can fire a new one."""
    dedupe_key = f"{monitor.monitor_id}:scan_failure:exhausted"
    existing = await session.execute(
        select(AlertEventRecord).where(
            AlertEventRecord.dedupe_key == dedupe_key,
            AlertEventRecord.state == AlertState.PENDING.value,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    now = datetime.now(UTC)
    session.add(
        AlertEventRecord(
            alert_id=uuid.uuid4(),
            org_id=monitor.org_id,
            monitor_id=monitor.monitor_id,
            type=AlertType.SCAN_FAILURE.value,
            state=AlertState.PENDING.value,
            severity=Severity.HIGH.value,
            subject=f"{monitor.hostname} — scan failed after retries",
            dedupe_key=dedupe_key,
            scheduled_for=now,
            sent_at=None,
            # Step 5 resolves real AlertRecipient rows before delivery —
            # nothing sends off a `pending` event, so an empty list here
            # is not a bug, just unfinished by design until that step.
            recipients=[],
            payload={"hostname": monitor.hostname, "monitor_id": str(monitor.monitor_id)},
        )
    )


async def record_scan_failure(session: AsyncSession, scan_record: ScanRecord) -> None:
    """Called by `scanner/orchestrator.py`'s `_mark_failed` for any failed
    scan tied to a monitor (scheduled or manual — both count toward the
    same retry streak). Advances `consecutive_failures`; while under the
    retry ceiling, reschedules the monitor at the matching backoff delay
    so the next scheduler tick retries it — the scheduler's own 5-minute
    polling cadence *is* the retry mechanism, no separate retry job exists.
    Once exhausted, fires the `scan_failure` alert instead of rescheduling
    early (the monitor still resumes its normal interval, already set at
    claim time by app/scheduler.py, or immediately for a manual rescan's
    failure — see routers/monitors.py)."""
    if scan_record.monitor_id is None:
        return
    monitor = await session.get(MonitoredHostnameRecord, scan_record.monitor_id)
    if monitor is None:
        return

    monitor.last_scanned_at = datetime.now(UTC)
    monitor.consecutive_failures += 1

    if monitor.consecutive_failures <= len(FAILURE_BACKOFF_SECONDS):
        backoff = FAILURE_BACKOFF_SECONDS[monitor.consecutive_failures - 1]
        monitor.next_scan_at = datetime.now(UTC) + timedelta(seconds=backoff)
    else:
        await _fire_scan_failure_alert(session, monitor)

    await session.commit()


# --- shared scan-record creation (manual rescan and, via app/scheduler.py,
# a scheduled one both go through this — no parallel code path) ---

_SLUG_LENGTH = 12
_SLUG_ALPHABET = string.ascii_letters + string.digits
_MAX_SLUG_ATTEMPTS = 8


def _generate_public_slug() -> str:
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(_SLUG_LENGTH))


async def create_monitor_scan_record(
    session: AsyncSession, monitor: MonitoredHostnameRecord, *, client_ip_hash: str | None
) -> ScanRecord:
    """Creates a queued `scans` row with `monitor_id` set. `client_ip_hash`
    is `None` for a scheduler-triggered scan (nothing to hash — Step 4's
    cron job, not a request) and a real hash for a manual rescan
    (`create_manual_rescan` below), mirroring `routers/scans.py`'s own
    scan-record creation (same public_slug collision-retry mechanics)."""
    for _ in range(_MAX_SLUG_ATTEMPTS):
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=_generate_public_slug(),
            hostname=monitor.hostname,
            port=monitor.port,
            status=ScanStatus.QUEUED.value,
            client_ip_hash=client_ip_hash,
            monitor_id=monitor.monitor_id,
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(record)
        return record

    raise ApiException(
        ErrorCode.INTERNAL_ERROR, "Could not allocate a unique share link. Try again."
    )


async def create_manual_rescan(
    session: AsyncSession, monitor: MonitoredHostnameRecord, *, client_ip: str
) -> ScanRecord:
    """Creates a queued `scans` row with `monitor_id` set for §7.8's manual
    re-scan endpoint."""
    ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    return await create_monitor_scan_record(session, monitor, client_ip_hash=ip_hash)
