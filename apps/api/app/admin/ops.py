"""Operational health for `GET /api/v1/admin/health` (contract §7.13).

"So I find out before a customer does." A stuck scheduler is the worst
silent failure this product has, so `monitors_overdue_1h` is computed
distinctly and the frontend renders it in red.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import AlertState, MonitorState, ScanStatus
from app.models import AlertEventRecord, MonitoredHostnameRecord, ScanRecord
from app.schemas import (
    AdminAlertQueueStatus,
    AdminHealthReport,
    AdminScans24h,
    AdminSchedulerStatus,
    AdminWorkerStatus,
)

logger = logging.getLogger("app.admin.ops")

# A scan still queued/running this long past its own whole-scan budget
# (§10 rule 5) is stuck, not slow.
_STUCK_GRACE_SECONDS = 60
# The scheduler tick runs every 5 minutes. "Overdue" allows a few missed
# ticks before flagging; "overdue by more than an hour" is the alarm.
_OVERDUE_AFTER = timedelta(minutes=15)
_OVERDUE_1H_AFTER = timedelta(hours=1)
# arq's default queue key — the sorted set holding queued and delayed jobs.
_ARQ_QUEUE_KEY = "arq:queue"


async def _ping_redis(redis: Redis) -> Literal["ok", "error"]:
    try:
        await redis.ping()
    except Exception:
        return "error"
    return "ok"


async def _last_scheduler_run(session: AsyncSession) -> datetime | None:
    """The most recent time the scheduler actually enqueued a scan (§7.13).
    A scheduler-originated scan is monitor-linked with no client IP hash
    (app/monitors.py's create_monitor_scan_record passes client_ip_hash=None;
    a manual re-scan passes a real hash). Null — "unknown" — until the
    scheduler has run at least once. Derived from `scans` rather than a
    heartbeat key so it can't drift out of sync with what the scheduler has
    really done."""
    value = (
        await session.execute(
            select(func.max(ScanRecord.created_at)).where(
                ScanRecord.monitor_id.is_not(None),
                ScanRecord.client_ip_hash.is_(None),
            )
        )
    ).scalar_one_or_none()
    return value


async def _read_queue_depth(redis: Redis) -> int:
    try:
        return int(await redis.zcard(_ARQ_QUEUE_KEY))
    except Exception:
        return 0


async def _scans_24h(session: AsyncSession, now: datetime) -> AdminScans24h:
    since = now - timedelta(hours=24)
    rows = (
        await session.execute(
            select(ScanRecord.status, func.count())
            .where(ScanRecord.created_at >= since)
            .group_by(ScanRecord.status)
        )
    ).all()
    by_status = {status: int(count) for status, count in rows}

    stuck_cutoff = now - timedelta(
        seconds=get_settings().scan_timeout_seconds + _STUCK_GRACE_SECONDS
    )
    stuck = (
        await session.execute(
            select(func.count())
            .select_from(ScanRecord)
            .where(
                ScanRecord.status.in_([ScanStatus.QUEUED.value, ScanStatus.RUNNING.value]),
                ScanRecord.created_at < stuck_cutoff,
            )
        )
    ).scalar_one()

    return AdminScans24h(
        completed=by_status.get(ScanStatus.COMPLETED.value, 0),
        failed=by_status.get(ScanStatus.FAILED.value, 0),
        queued=by_status.get(ScanStatus.QUEUED.value, 0),
        running=by_status.get(ScanStatus.RUNNING.value, 0),
        stuck=int(stuck),
    )


async def _scheduler_counts(session: AsyncSession, now: datetime) -> tuple[int, int, int]:
    async def _count_active_before(cutoff: datetime) -> int:
        value = (
            await session.execute(
                select(func.count())
                .select_from(MonitoredHostnameRecord)
                .where(
                    MonitoredHostnameRecord.state == MonitorState.ACTIVE.value,
                    MonitoredHostnameRecord.next_scan_at.is_not(None),
                    MonitoredHostnameRecord.next_scan_at <= cutoff,
                )
            )
        ).scalar_one()
        return int(value)

    due = await _count_active_before(now)
    overdue = await _count_active_before(now - _OVERDUE_AFTER)
    overdue_1h = await _count_active_before(now - _OVERDUE_1H_AFTER)
    return due, overdue, overdue_1h


async def _alert_counts(session: AsyncSession, now: datetime) -> tuple[int, int]:
    since = now - timedelta(hours=24)
    pending = (
        await session.execute(
            select(func.count())
            .select_from(AlertEventRecord)
            .where(AlertEventRecord.state == AlertState.PENDING.value)
        )
    ).scalar_one()
    failed_24h = (
        await session.execute(
            select(func.count())
            .select_from(AlertEventRecord)
            .where(
                AlertEventRecord.state == AlertState.FAILED.value,
                AlertEventRecord.created_at >= since,
            )
        )
    ).scalar_one()
    return int(pending), int(failed_24h)


async def build_health_report(session: AsyncSession, redis: Redis) -> AdminHealthReport:
    now = datetime.now(UTC)

    redis_status = await _ping_redis(redis)
    queue_depth = await _read_queue_depth(redis)

    postgres_status: Literal["ok", "error"] = "ok"
    last_run: datetime | None = None
    try:
        await session.execute(text("SELECT 1"))
        scans_24h = await _scans_24h(session, now)
        due, overdue, overdue_1h = await _scheduler_counts(session, now)
        pending, failed_24h = await _alert_counts(session, now)
        last_run = await _last_scheduler_run(session)
    except SQLAlchemyError:
        logger.exception("admin_health_db_metrics_failed")
        postgres_status = "error"
        scans_24h = AdminScans24h(completed=0, failed=0, queued=0, running=0, stuck=0)
        due = overdue = overdue_1h = 0
        pending = failed_24h = 0

    return AdminHealthReport(
        generated_at=now,
        scans_24h=scans_24h,
        scheduler=AdminSchedulerStatus(
            monitors_due=due,
            monitors_overdue=overdue,
            monitors_overdue_1h=overdue_1h,
            last_successful_run_at=last_run,
        ),
        alert_queue=AdminAlertQueueStatus(pending=pending, failed_24h=failed_24h),
        worker=AdminWorkerStatus(queue_depth=queue_depth, memory_mb=None),
        redis=redis_status,
        postgres=postgres_status,
    )
