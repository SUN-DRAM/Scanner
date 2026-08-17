"""arq worker entrypoint (contract §3.2). Run via `arq app.worker.WorkerSettings`
(the `worker` service in docker-compose.yml).

The only job this queue ever processes is `run_scan_job`: run the full scan
for an already-`queued` `scans` row and persist the result. All status
transitions (`queued` -> `running` -> `completed`/`failed`) happen inside
`app.scanner.orchestrator.run_scan` itself — this function is a thin async
entrypoint that gives it a database session.
"""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.alerts import deliver_pending_alerts
from app.billing.service import expire_due_cancellations
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging_config import configure_logging
from app.notify.email import get_email_sender
from app.observability import init_sentry
from app.scanner.orchestrator import run_scan
from app.scheduler import run_scheduler_tick

_settings = get_settings()
configure_logging(_settings)
init_sentry(_settings)

_EVERY_FIVE_MINUTES = set(range(0, 60, 5))


async def run_scan_job(_ctx: dict[str, Any], scan_id: str) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await run_scan(session, scan_id)


async def deliver_alerts_tick(_ctx: dict[str, Any]) -> None:
    """§Step 5: alert delivery, on the same 5-minute cadence as the
    scheduler tick — a distinct cron job (not folded into
    run_scheduler_tick) so scanning and alerting stay two concerns, not
    one function doing both."""
    sessionmaker = get_sessionmaker()
    email_sender = get_email_sender(get_settings())
    async with sessionmaker() as session:
        await deliver_pending_alerts(session, email_sender)


async def expire_subscriptions_tick(_ctx: dict[str, Any]) -> None:
    """§7.11: a `cancel_at_period_end` subscription whose `current_period_end`
    has actually passed reverts its org to `free` and quota-blocks the
    excess (§7.8's downgrade rule) — the part of "never immediate" that a
    webhook alone can't guarantee happens if the provider's own end-of-period
    event is late or never arrives. Same 5-minute cadence as the other two
    cron jobs, a distinct job for the same reason `deliver_alerts_tick` is
    distinct from `run_scheduler_tick`."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await expire_due_cancellations(session)


class WorkerSettings:
    functions = (run_scan_job,)
    # §Step 4: "An arq cron job every 5 minutes claiming due monitors and
    # enqueuing scans." run_scheduler_tick (app/scheduler.py) does the
    # claiming; this only fires it on the clock. deliver_alerts_tick
    # (§Step 5) is the same cadence, a separate job.
    _scheduler_cron_job = cron(run_scheduler_tick, minute=_EVERY_FIVE_MINUTES)
    # mypy flags this second cron() call but not the first, despite
    # deliver_alerts_tick and run_scheduler_tick having the exact same
    # `async def f(ctx: dict[str, Any]) -> None` shape (confirmed by
    # isolating both against arq.typing.WorkerCoroutine directly) — a
    # false positive in how mypy resolves arq's stubs for this specific
    # pattern, not a real signature mismatch.
    _alerts_cron_job = cron(deliver_alerts_tick, minute=_EVERY_FIVE_MINUTES)  # type: ignore[arg-type]
    _billing_cron_job = cron(expire_subscriptions_tick, minute=_EVERY_FIVE_MINUTES)  # type: ignore[arg-type]
    cron_jobs = [_scheduler_cron_job, _alerts_cron_job, _billing_cron_job]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Comfortably above SCAN_TIMEOUT_SECONDS so the orchestrator's own
    # whole-scan budget (§10 rule 5) is always what actually cuts a stuck
    # scan short, not arq's job timeout racing it.
    job_timeout = get_settings().scan_timeout_seconds + 10
    # §Step 4: "bound worker concurrency explicitly and confirm memory
    # headroom under a full scheduled cycle." This cap is shared by every
    # job this worker runs — public scans, manual re-scans, and scheduled
    # ones alike — which is why app/scheduler.py additionally caps
    # concurrent *scheduled* scans at Settings.scheduler_max_concurrent_
    # scans (default 3, well under this 10): a full scheduled backlog can
    # never claim more than 3 of these 10 slots, leaving at least 7 always
    # free for public/manual traffic. docker-compose.prod.yml already caps
    # this container at 768M/1 vCPU (Gate C) — confirming that ceiling
    # holds under a real full scheduled cycle on the production instance is
    # an operational verification this repo can't perform from here, and is
    # called out as a deploy follow-up rather than silently assumed done.
    max_jobs = 10
