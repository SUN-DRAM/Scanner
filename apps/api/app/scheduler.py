"""Phase 2 Step 4: the arq cron job that claims due `MonitoredHostname`s and
enqueues scans for them, registered in `app/worker.py`.

Reuses `app.monitors.create_monitor_scan_record` for the actual `scans` row
— the same function a manual re-scan (`app.monitors.create_manual_rescan`)
goes through — so a scheduled scan and a manual one are never two code
paths for the part that matters (§Step 3's "no parallel code path" rule,
extended here rather than re-litigated).
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import ArqRedis
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_sessionmaker
from app.enums import MonitorState, PlanCode
from app.models import MonitoredHostnameRecord, OrganisationRecord
from app.monitors import create_monitor_scan_record
from app.plans import get_plan

logger = logging.getLogger("app.scheduler")

# Redis sorted-set semaphore bounding how many scheduler-enqueued scans may
# be in flight at once (§Step 4: "Global concurrency cap via a Redis
# semaphore. A scheduled backlog must never starve interactive public
# scans"). Self-expiring rather than explicitly released when a scan
# finishes: a worker crash mid-scan would otherwise leak the slot forever.
# A scan almost always finishes well inside this window (SCAN_TIMEOUT_
# SECONDS defaults to 25s) — the tradeoff is a slot staying "reserved" for
# the rest of the TTL even after the scan finishes early, which only means
# slightly fewer scheduled scans start on the very next tick, never a
# correctness problem. Deliberately never shared with public/manual
# scans — those have no budget here at all, which is what guarantees they
# can never be starved by this one (see Settings.scheduler_max_concurrent_
# scans in app/config.py, well under worker.py's max_jobs=10).
_INFLIGHT_KEY = "scheduler:inflight"
_INFLIGHT_TTL_SECONDS = 600

JITTER_FRACTION = 0.10  # ±10% (§Step 4)

# Not specified by the phase prompt: a plan with no numeric scan interval
# (secure/compliance — Phase 3, not purchasable yet, see app/plans.py)
# falls back to watch's 6h rather than a monitor silently never being
# rescheduled. No org can actually be on either plan in Phase 2, so this
# branch is unreachable today; it exists so a future org on one of them
# doesn't go dark instead of erroring loudly.
_FALLBACK_SCAN_INTERVAL_HOURS = 6


def _jittered_interval(hours: int) -> timedelta:
    base_seconds = hours * 3600
    jitter_seconds = base_seconds * random.uniform(-JITTER_FRACTION, JITTER_FRACTION)
    return timedelta(seconds=base_seconds + jitter_seconds)


async def _available_capacity(redis: Redis, max_concurrent: int) -> int:
    now = datetime.now(UTC).timestamp()
    await redis.zremrangebyscore(_INFLIGHT_KEY, 0, now)
    in_flight = int(await redis.zcard(_INFLIGHT_KEY))
    return max(0, max_concurrent - in_flight)


async def _reserve_capacity(redis: Redis, scan_id: uuid.UUID) -> None:
    expiry = datetime.now(UTC).timestamp() + _INFLIGHT_TTL_SECONDS
    await redis.zadd(_INFLIGHT_KEY, {str(scan_id): expiry})


async def claim_due_monitors(
    session: AsyncSession, redis: Redis, arq_pool: ArqRedis, *, max_concurrent: int
) -> int:
    """One scheduler tick. Claims up to the currently available semaphore
    capacity, reserves each claimed monitor's next slot immediately — so a
    scan that outlives one 5-minute tick is never claimed a second time —
    and enqueues a scan for each. Returns how many were claimed, for
    logging. `redis` and `arq_pool` are accepted separately (rather than
    assuming one object satisfies both) purely for testability — in
    production (`run_scheduler_tick` below) the same `ArqRedis` connection
    satisfies both.
    """
    capacity = await _available_capacity(redis, max_concurrent)
    if capacity <= 0:
        return 0

    now = datetime.now(UTC)
    stmt = (
        select(MonitoredHostnameRecord)
        .where(
            MonitoredHostnameRecord.state == MonitorState.ACTIVE.value,
            MonitoredHostnameRecord.next_scan_at.is_not(None),
            MonitoredHostnameRecord.next_scan_at <= now,
        )
        .order_by(MonitoredHostnameRecord.next_scan_at.asc())
        .limit(capacity)
        # §Step 4: "Claim with SELECT ... FOR UPDATE SKIP LOCKED so two
        # workers never scan the same monitor" — a second concurrent tick
        # (or a second worker process) simply skips any row this one
        # already has locked, rather than blocking on it.
        .with_for_update(skip_locked=True)
    )
    monitors = (await session.execute(stmt)).scalars().all()
    if not monitors:
        return 0

    org_ids = {monitor.org_id for monitor in monitors}
    orgs_stmt = select(OrganisationRecord).where(OrganisationRecord.org_id.in_(org_ids))
    orgs_by_id = {org.org_id: org for org in (await session.execute(orgs_stmt)).scalars().all()}

    claimed = 0
    for monitor in monitors:
        org = orgs_by_id.get(monitor.org_id)
        interval_hours = None
        if org is not None:
            interval_hours = get_plan(PlanCode(org.plan_code)).scan_interval_hours
        effective_hours = interval_hours or _FALLBACK_SCAN_INTERVAL_HOURS

        # Reserving the next slot now, before the scan even runs, is what
        # makes this a claim: the row is due again only after a full
        # interval from now, regardless of how long this scan takes.
        monitor.next_scan_at = now + _jittered_interval(effective_hours)
        await session.commit()

        scan_record = await create_monitor_scan_record(session, monitor, client_ip_hash=None)
        await _reserve_capacity(redis, scan_record.scan_id)
        await arq_pool.enqueue_job("run_scan_job", str(scan_record.scan_id))
        claimed += 1

    return claimed


async def run_scheduler_tick(ctx: dict[str, Any]) -> None:
    """arq cron entrypoint (registered in app/worker.py), running every 5
    minutes (§Step 4). `ctx["redis"]` is arq's own worker-managed
    connection — an `ArqRedis`, itself a `redis.asyncio.Redis` subclass —
    reused for both the semaphore and enqueueing, so no second Redis
    connection is opened just for this."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    arq_pool: ArqRedis = ctx["redis"]

    async with sessionmaker() as session:
        claimed = await claim_due_monitors(
            session, arq_pool, arq_pool, max_concurrent=settings.scheduler_max_concurrent_scans
        )
    if claimed:
        logger.info("scheduler_tick_claimed_monitors", extra={"claimed": claimed})
