"""docs/urgent_scan_corruption.md Finding 4, Step 1.1: a failure in a
post-success side effect (alert evaluation, monitor bookkeeping) must never
be able to overwrite an already-completed, already-persisted scan back to
`failed`. Exercises the real `run_scan` entry point against a real DB, with
the module fan-out and hostname resolution mocked so this stays
network-free like the rest of the DB-backed test suite.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ScanStatus
from app.models import MonitoredHostnameRecord, OrganisationRecord, ScanRecord
from app.scanner.orchestrator import run_scan
from tests.pdf_fixtures import default_modules


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


async def _make_queued_scan(session: AsyncSession, monitor: MonitoredHostnameRecord) -> ScanRecord:
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=monitor.hostname,
        port=monitor.port,
        status=ScanStatus.QUEUED.value,
        monitor_id=monitor.monitor_id,
    )
    session.add(record)
    await session.commit()
    return record


@pytest.mark.asyncio
async def test_a_crash_in_alert_evaluation_does_not_overwrite_a_completed_scan(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    record = await _make_queued_scan(db_session, monitor)

    with (
        patch(
            "app.scanner.orchestrator.resolve_and_validate",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.scanner.orchestrator._run_all_modules",
            new=AsyncMock(return_value=default_modules()),
        ),
        patch(
            "app.scanner.orchestrator.evaluate_and_fire_alerts",
            new=AsyncMock(side_effect=RuntimeError("simulated pre-v3.0 row ValidationError")),
        ),
    ):
        scan = await run_scan(db_session, str(record.scan_id))

    # The scan itself must report success — alert evaluation is a
    # consequence of it, not part of producing it.
    assert scan.status == ScanStatus.COMPLETED
    assert scan.overall_grade is not None

    await db_session.refresh(record)
    assert record.status == ScanStatus.COMPLETED.value
    assert record.overall_grade is not None
    assert record.result is not None
    assert record.result["status"] == "completed"


@pytest.mark.asyncio
async def test_a_crash_in_monitor_update_does_not_overwrite_a_completed_scan(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    record = await _make_queued_scan(db_session, monitor)

    with (
        patch(
            "app.scanner.orchestrator.resolve_and_validate",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.scanner.orchestrator._run_all_modules",
            new=AsyncMock(return_value=default_modules()),
        ),
        patch(
            "app.scanner.orchestrator.update_monitor_after_scan",
            new=AsyncMock(side_effect=RuntimeError("simulated failure")),
        ),
    ):
        scan = await run_scan(db_session, str(record.scan_id))

    assert scan.status == ScanStatus.COMPLETED
    await db_session.refresh(record)
    assert record.status == ScanStatus.COMPLETED.value
