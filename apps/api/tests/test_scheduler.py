"""Tests for app/scheduler.py (contract §Step 4 / §7.9): claiming due
monitors, jitter bounds, the Redis concurrency semaphore, and that a row
already locked by another transaction is skipped, not blocked on.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.models import MonitoredHostnameRecord, OrganisationRecord, ScanRecord
from app.scheduler import _INFLIGHT_KEY, _jittered_interval, claim_due_monitors
from tests.conftest import FakeArqPool


async def _make_org(session: AsyncSession, *, plan_code: str = "free") -> OrganisationRecord:
    org = OrganisationRecord(
        org_id=uuid.uuid4(), name="Acme", country="IN", currency="INR", plan_code=plan_code
    )
    session.add(org)
    await session.commit()
    return org


async def _make_monitor(
    session: AsyncSession, org: OrganisationRecord, *, next_scan_at: datetime | None
) -> MonitoredHostnameRecord:
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(),
        org_id=org.org_id,
        hostname=f"{uuid.uuid4().hex}.example.com",
        port=443,
        state="active",
        next_scan_at=next_scan_at,
    )
    session.add(monitor)
    await session.commit()
    return monitor


@pytest.fixture(autouse=True)
async def _reset_inflight_semaphore(redis_client: Redis) -> AsyncGenerator[None]:
    yield
    await redis_client.delete(_INFLIGHT_KEY)


@pytest.fixture(autouse=True)
async def _clear_stale_due_monitors(db_session: AsyncSession) -> None:
    # claim_due_monitors queries globally across every org, by design — the
    # same real Postgres database other test files' monitors (e.g.
    # test_monitors_router.py's create_monitor calls, which set
    # next_scan_at=now) persist in between runs, since nothing there ever
    # deletes them. Without this, a due-monitor count from an unrelated
    # file would leak into these tests' claim counts.
    stale_ids_stmt = select(MonitoredHostnameRecord.monitor_id).where(
        MonitoredHostnameRecord.state == "active",
        MonitoredHostnameRecord.next_scan_at <= datetime.now(UTC),
    )
    stale_ids = (await db_session.execute(stale_ids_stmt)).scalars().all()
    if stale_ids:
        await db_session.execute(
            delete(ScanRecord).where(ScanRecord.monitor_id.in_(stale_ids))
        )
        await db_session.execute(
            delete(MonitoredHostnameRecord).where(
                MonitoredHostnameRecord.monitor_id.in_(stale_ids)
            )
        )
        await db_session.commit()


def test_jittered_interval_stays_within_plus_minus_ten_percent() -> None:
    base = timedelta(hours=6).total_seconds()
    for _ in range(200):
        jittered = _jittered_interval(6).total_seconds()
        assert base * 0.9 <= jittered <= base * 1.1


@pytest.mark.asyncio
async def test_claim_due_monitors_claims_due_and_leaves_future_ones_alone(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    org = await _make_org(db_session)
    due = await _make_monitor(
        db_session, org, next_scan_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    future_time = datetime.now(UTC) + timedelta(hours=1)
    not_due = await _make_monitor(db_session, org, next_scan_at=future_time)
    arq_pool = FakeArqPool()

    claimed = await claim_due_monitors(db_session, redis_client, arq_pool, max_concurrent=10)

    assert claimed == 1
    assert len(arq_pool.enqueued) == 1
    assert arq_pool.enqueued[0][0] == "run_scan_job"

    await db_session.refresh(due)
    await db_session.refresh(not_due)
    # Reserved forward to roughly a fresh free-plan interval (24h ± 10%),
    # so it is not immediately due again.
    assert due.next_scan_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(hours=20)
    # Untouched — it wasn't due, so it wasn't claimed.
    assert not_due.next_scan_at.replace(tzinfo=UTC) == future_time


@pytest.mark.asyncio
async def test_claim_due_monitors_respects_the_concurrency_cap(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    org = await _make_org(db_session)
    for _ in range(3):
        await _make_monitor(
            db_session, org, next_scan_at=datetime.now(UTC) - timedelta(minutes=1)
        )
    arq_pool = FakeArqPool()

    claimed = await claim_due_monitors(db_session, redis_client, arq_pool, max_concurrent=2)

    assert claimed == 2
    assert len(arq_pool.enqueued) == 2


@pytest.mark.asyncio
async def test_claim_due_monitors_returns_zero_when_capacity_already_exhausted(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    org = await _make_org(db_session)
    await _make_monitor(db_session, org, next_scan_at=datetime.now(UTC) - timedelta(minutes=1))
    # Pre-fill the semaphore to its cap.
    expiry = datetime.now(UTC).timestamp() + 600
    await redis_client.zadd(_INFLIGHT_KEY, {"already-in-flight": expiry})
    arq_pool = FakeArqPool()

    claimed = await claim_due_monitors(db_session, redis_client, arq_pool, max_concurrent=1)

    assert claimed == 0
    assert arq_pool.enqueued == []


@pytest.mark.asyncio
async def test_claim_due_monitors_skips_a_row_locked_by_another_transaction(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(
        db_session, org, next_scan_at=datetime.now(UTC) - timedelta(minutes=1)
    )

    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as locking_conn:
            # Holds the row lock open — no commit yet — for the duration of
            # this block, simulating a second worker's in-progress claim.
            await locking_conn.execute(
                text("SELECT * FROM monitored_hostnames WHERE monitor_id = :id FOR UPDATE"),
                {"id": str(monitor.monitor_id)},
            )

            arq_pool = FakeArqPool()
            claimed = await claim_due_monitors(
                db_session, redis_client, arq_pool, max_concurrent=10
            )

            # §Step 4: "SELECT ... FOR UPDATE SKIP LOCKED so two workers
            # never scan the same monitor" — skipped, not blocked on.
            assert claimed == 0
            assert arq_pool.enqueued == []
    finally:
        await engine.dispose()
