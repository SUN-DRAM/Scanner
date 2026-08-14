"""Tests for app/monitors.py's post-scan hooks: update_monitor_after_scan
(success, contract §6.9) and record_scan_failure (retry backoff, then a
scan_failure AlertEvent once retries are exhausted, contract §Step 4/§7.9).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AlertState, AlertType, Grade, ScanStatus
from app.models import AlertEventRecord, MonitoredHostnameRecord, OrganisationRecord, ScanRecord
from app.monitors import FAILURE_BACKOFF_SECONDS, record_scan_failure, update_monitor_after_scan


async def _make_org(session: AsyncSession) -> OrganisationRecord:
    org = OrganisationRecord(
        org_id=uuid.uuid4(), name="Acme", country="IN", currency="INR", plan_code="free"
    )
    session.add(org)
    await session.commit()
    return org


async def _make_monitor(session: AsyncSession, org: OrganisationRecord) -> MonitoredHostnameRecord:
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(),
        org_id=org.org_id,
        hostname=f"{uuid.uuid4().hex}.example.com",
        port=443,
        state="active",
    )
    session.add(monitor)
    await session.commit()
    return monitor


async def _make_scan(session: AsyncSession, monitor: MonitoredHostnameRecord) -> ScanRecord:
    scan = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=monitor.hostname,
        port=monitor.port,
        status=ScanStatus.FAILED.value,
        monitor_id=monitor.monitor_id,
    )
    session.add(scan)
    await session.commit()
    return scan


async def _alerts_for(session: AsyncSession, monitor_id: uuid.UUID) -> list[AlertEventRecord]:
    stmt = select(AlertEventRecord).where(AlertEventRecord.monitor_id == monitor_id)
    return list((await session.execute(stmt)).scalars().all())


@pytest.mark.asyncio
async def test_update_monitor_after_scan_resets_the_failure_streak(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    monitor.consecutive_failures = 2
    await db_session.commit()
    scan = await _make_scan(db_session, monitor)

    not_after = datetime.now(UTC) + timedelta(days=30)
    await update_monitor_after_scan(
        db_session,
        scan,
        grade=Grade.A,
        score=95,
        cert_not_after=not_after,
        scanned_at=datetime.now(UTC),
    )

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 0
    assert monitor.last_scan_id == scan.scan_id
    assert monitor.last_grade == "A"
    assert monitor.last_score == 95
    assert monitor.cert_not_after is not None


@pytest.mark.asyncio
async def test_record_scan_failure_schedules_a_backoff_retry_before_exhausted(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    scan = await _make_scan(db_session, monitor)

    before = datetime.now(UTC)
    await record_scan_failure(db_session, scan)

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 1
    assert monitor.next_scan_at is not None
    expected = before + timedelta(seconds=FAILURE_BACKOFF_SECONDS[0])
    assert abs((monitor.next_scan_at.replace(tzinfo=UTC) - expected).total_seconds()) < 5

    assert await _alerts_for(db_session, monitor.monitor_id) == []


@pytest.mark.asyncio
async def test_record_scan_failure_fires_an_alert_once_retries_are_exhausted(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    monitor.consecutive_failures = len(FAILURE_BACKOFF_SECONDS)  # one short of exhausted
    await db_session.commit()
    scan = await _make_scan(db_session, monitor)

    await record_scan_failure(db_session, scan)

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == len(FAILURE_BACKOFF_SECONDS) + 1

    alerts = await _alerts_for(db_session, monitor.monitor_id)
    assert len(alerts) == 1
    assert alerts[0].type == AlertType.SCAN_FAILURE.value
    assert alerts[0].state == AlertState.PENDING.value
    assert alerts[0].dedupe_key == f"{monitor.monitor_id}:scan_failure:exhausted"
    assert alerts[0].org_id == org.org_id


@pytest.mark.asyncio
async def test_record_scan_failure_does_not_duplicate_a_pending_alert(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    monitor.consecutive_failures = len(FAILURE_BACKOFF_SECONDS) + 5  # already well exhausted
    await db_session.commit()

    await record_scan_failure(db_session, await _make_scan(db_session, monitor))
    await record_scan_failure(db_session, await _make_scan(db_session, monitor))

    alerts = await _alerts_for(db_session, monitor.monitor_id)
    assert len(alerts) == 1
