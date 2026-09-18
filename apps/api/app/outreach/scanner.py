"""Stage 2 batch scan runner (contract §7.16, spec §8). A periodic arq
cron tick — `outreach_scan_tick`, registered in `app/worker.py` — not one
long-running job per batch.

**Why a tick, not a single job that walks the whole batch.** arq's
`job_timeout` (`app/worker.py`) is one fixed value shared by every job
type this worker runs, sized for a single scan (`scan_timeout_seconds +
10`, ~35s) — this arq version's `enqueue_job` has no per-call override.
A ~40-minute job would be killed by that timeout long before it finished.
Every scan this module ever runs goes through the *existing* `run_scan_job`
(unchanged, shared with public and monitor scans) — well inside that
budget — enqueued from here exactly as `app/scheduler.py` already enqueues
one for a due monitor. This is also the literal reading of the stage
prompt's own words: "same mechanism the monitor scheduler uses," "exactly
as scheduled monitor scans already do" — not merely similar, the same
job, the same Redis-semaphore pattern, the same `SELECT ... FOR UPDATE
SKIP LOCKED` claim.

**Settlement is polled, not pushed.** `run_scan_job` knows nothing about
`outreach_domains` — deliberately: spec §2.1 keeps the orchestrator free
of outreach-specific logic. Each tick instead reconciles every domain
currently `RUNNING` against its linked `scans` row's actual status. A
domain whose scan hasn't finished yet is left alone; one whose scan
finished (or has been running suspiciously long — see the staleness note
below) is settled into `COMPLETED`/`COMPLETED_PARTIAL`/`RETRYING`/`FAILED`
through Stage 1's state machine, never by ad hoc assignment.

**Crash recovery.** A `RUNNING` domain whose linked scan is itself still
`queued`/`running` in the database, but older than `scan_timeout_seconds +
_STALE_GRACE_SECONDS`, is treated as an attempt the worker crashed on —
same `_STUCK_GRACE_SECONDS` constant and threshold `app/admin/ops.py`
already uses for the public "stuck scan" signal, reused here rather than
inventing a second number. It's retried (or failed, if retries are
exhausted) exactly like a genuine scan failure. This is what makes "kill
the worker mid-batch and restart" (the stage prompt's own verification
line) actually resolve: the next tick after a restart reclaims it.
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import ArqRedis
from redis.asyncio import Redis
from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.enums import (
    OutreachCampaignStatus,
    OutreachDomainState,
    OutreachProspectState,
    ScanStatus,
)
from app.models import (
    OutreachCampaignRecord,
    OutreachDomainRecord,
    OutreachProspectRecord,
    ScanRecord,
)
from app.outreach.state_machine import transition_domain, transition_prospect
from app.scan_compat import parse_stored_scan

logger = logging.getLogger("app.outreach.scanner")

# Same convention `app/admin/ops.py`'s public "stuck scan" signal already
# established: a scan running longer than scan_timeout_seconds plus this
# grace period is not slow, it's stuck (or its worker died).
_STALE_GRACE_SECONDS = 60

# Spec §5.2 / stage prompt Step 3: a COMPLETED_PARTIAL domain gets exactly
# one re-scan, never governed by OUTREACH_MAX_SCAN_RETRIES (that number is
# about genuine failures). Eligible for its one retry only while
# scan_attempts is still 1 (its first, and only, attempt so far).
_COMPLETED_PARTIAL_RETRY_AT_ATTEMPTS = 1

# outreach_domains has no port column (contract §11) — every outreach scan
# runs on 443, the same assumption the Stage 1 CSV importer's hostname
# validation already made implicitly (§7.2 normalisation accepts a port
# suffix and validates it, but nothing downstream of import stores one).
_DEFAULT_PORT = 443

# Redis sorted-set semaphore — a separate key and separate budget
# (OUTREACH_MAX_CONCURRENT_SCANS, not SCHEDULER_MAX_CONCURRENT_SCANS),
# never shared with app/scheduler.py's own _INFLIGHT_KEY, which is what
# guarantees a batch can't starve scheduled scans any more than it can
# starve public ones.
#
# Deliberately **not** a copy of the scheduler's TTL value, despite the
# identical mechanism otherwise. The scheduler releases a slot purely by
# TTL expiry (600s) and accepts the slack as harmless — its concurrency
# budget (3) is generous against a scan cadence measured in hours. Found
# live, not by inspection: copying that same 600s TTL here, with a budget
# of 2 concurrent slots and a 15s pacing goal, meant a slot reserved at
# claim time never freed up until the *TTL* elapsed regardless of how
# quickly the scan actually finished — at most 2 domains could ever scan
# in the first 10 minutes of any batch, no matter how fast each one
# completed. Fixed by releasing each slot explicitly the moment its domain
# settles (`_release_capacity`, called from `_reconcile_running_domain`),
# with the TTL kept only as a crash backstop — sized just past the
# staleness threshold below, since anything older than that is already
# being reclaimed as a crashed attempt anyway.
_INFLIGHT_KEY = "outreach:inflight"

_SLUG_LENGTH = 12
_SLUG_ALPHABET = string.ascii_letters + string.digits
_MAX_SLUG_ATTEMPTS = 8


def _generate_public_slug() -> str:
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(_SLUG_LENGTH))


async def _create_outreach_scan_record(session: AsyncSession, hostname: str) -> ScanRecord:
    """A queued `scans` row for an outreach batch scan — `monitor_id` null,
    `client_ip_hash` null (a background job, not a request), same
    public_slug collision-retry as every other scan-record creation site
    in this codebase (`app/monitors.py`, `app/admin/prospects.py`,
    `app/routers/scans.py`) — a fourth copy of the same few lines rather
    than a shared helper, matching this codebase's existing per-module
    convention rather than introducing a new cross-cutting one."""
    for _ in range(_MAX_SLUG_ATTEMPTS):
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=_generate_public_slug(),
            hostname=hostname,
            port=_DEFAULT_PORT,
            status=ScanStatus.QUEUED.value,
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(record)
        return record

    raise RuntimeError(f"Could not allocate a unique public_slug for outreach scan of {hostname}")


async def _available_capacity(redis: Redis, max_concurrent: int) -> int:
    now = datetime.now(UTC).timestamp()
    await redis.zremrangebyscore(_INFLIGHT_KEY, 0, now)
    in_flight = int(await redis.zcard(_INFLIGHT_KEY))
    return max(0, max_concurrent - in_flight)


async def _reserve_capacity(redis: Redis, scan_id: uuid.UUID, *, settings: Settings) -> None:
    # TTL is a crash backstop, not the normal release path (see this
    # module's docstring note above) — sized just past the staleness
    # threshold `_reconcile_running_domain` already uses, since anything
    # older than that is already being reclaimed as a crashed attempt.
    ttl_seconds = settings.scan_timeout_seconds + _STALE_GRACE_SECONDS + 60
    expiry = datetime.now(UTC).timestamp() + ttl_seconds
    await redis.zadd(_INFLIGHT_KEY, {str(scan_id): expiry})


async def _release_capacity(redis: Redis, scan_id: uuid.UUID) -> None:
    """The normal release path — called the moment a domain settles, so a
    fast scan frees its slot immediately rather than waiting out the TTL
    backstop above."""
    await redis.zrem(_INFLIGHT_KEY, str(scan_id))


def _incomplete_module_summary(parsed: Any) -> str | None:
    """`completed_partial_by_module_error` (§7.16) reads this same data
    straight from the scan at report time — this summary is only for the
    domain's own `scan_error`, a human-readable trace for the recent-
    outcomes list, not the source of truth for that aggregate."""
    if not parsed.incomplete_modules:
        return None
    parts: list[str] = []
    for name in parsed.incomplete_modules:
        result = getattr(parsed.modules, name.value, None)
        if result is not None and result.error is not None:
            parts.append(f"{name.value}: {result.error.code.value}")
        else:
            parts.append(f"{name.value}: unknown")
    return "; ".join(parts) if parts else None


def _apply_retry_or_fail(
    domain: OutreachDomainRecord,
    *,
    reason: str,
    campaign_status: OutreachCampaignStatus,
    settings: Settings,
) -> None:
    """Retry-count semantics pinned down in CONTRACT.md §7.16:
    `scan_attempts` counts total attempts; `RETRYING` while it's still
    `<= OUTREACH_MAX_SCAN_RETRIES`, `FAILED` once it exceeds that — 1 +
    OUTREACH_MAX_SCAN_RETRIES total attempts before a domain is given up
    on."""
    if domain.scan_attempts <= settings.outreach_max_scan_retries:
        transition_domain(
            domain, OutreachDomainState.RETRYING, campaign_status=campaign_status, reason=reason
        )
    else:
        transition_domain(
            domain, OutreachDomainState.FAILED, campaign_status=campaign_status, reason=reason
        )


async def _reconcile_running_domain(
    session: AsyncSession,
    redis: Redis,
    domain: OutreachDomainRecord,
    *,
    campaign_status: OutreachCampaignStatus,
    settings: Settings,
) -> bool:
    """Returns True if the domain left RUNNING this call (settled or
    reclaimed), False if its scan is still legitimately in flight. Every
    True path releases this domain's semaphore slot immediately — see
    `_release_capacity`'s docstring on why that matters more here than it
    does for the scheduler's own, much slower-paced version of this."""
    scan_id = domain.scan_id

    if scan_id is None:
        # Should never happen — RUNNING is only ever entered alongside
        # setting scan_id in the same commit (claim_and_start_domains
        # below). Treated as a crashed attempt rather than raising, since
        # there is a real domain here that needs to not be stuck forever.
        _apply_retry_or_fail(
            domain,
            reason="RUNNING with no linked scan — treated as a crashed attempt",
            campaign_status=campaign_status,
            settings=settings,
        )
        return True

    scan = await session.get(ScanRecord, scan_id)
    if scan is None:
        _apply_retry_or_fail(
            domain,
            reason="linked scan record is missing — treated as a crashed attempt",
            campaign_status=campaign_status,
            settings=settings,
        )
        await _release_capacity(redis, scan_id)
        return True

    if scan.status == ScanStatus.COMPLETED.value:
        parsed = parse_stored_scan(scan.result or {})
        if parsed.is_complete:
            transition_domain(
                domain, OutreachDomainState.COMPLETED, campaign_status=campaign_status, reason=None
            )
        else:
            transition_domain(
                domain,
                OutreachDomainState.COMPLETED_PARTIAL,
                campaign_status=campaign_status,
                reason=_incomplete_module_summary(parsed),
            )
        await _release_capacity(redis, scan_id)
        return True

    if scan.status == ScanStatus.FAILED.value:
        reason = scan.error_message or scan.error_code or "scan failed"
        _apply_retry_or_fail(
            domain, reason=reason, campaign_status=campaign_status, settings=settings
        )
        await _release_capacity(redis, scan_id)
        return True

    # Still queued/running — legitimately in flight unless it's been going
    # on long enough that the worker running it almost certainly crashed.
    stale_cutoff = datetime.now(UTC) - timedelta(
        seconds=settings.scan_timeout_seconds + _STALE_GRACE_SECONDS
    )
    if scan.created_at < stale_cutoff:
        _apply_retry_or_fail(
            domain,
            reason="scan did not complete in time (stuck, or its worker crashed)",
            campaign_status=campaign_status,
            settings=settings,
        )
        await _release_capacity(redis, scan_id)
        return True

    return False


async def completed_domains_for_prospect(
    session: AsyncSession, prospect_id: uuid.UUID
) -> list[OutreachDomainRecord]:
    """Spec §5.2: a `COMPLETED_PARTIAL` domain is excluded from hook
    selection and from any attachment. Written now, ahead of Stage 3
    needing it, so hook selection literally cannot reach past it by
    querying domains directly instead — the one place "which domains are
    safe to cite" is decided."""
    rows = await session.execute(
        select(OutreachDomainRecord).where(
            OutreachDomainRecord.prospect_id == prospect_id,
            OutreachDomainRecord.state == OutreachDomainState.COMPLETED.value,
        )
    )
    return list(rows.scalars().all())


async def _maybe_roll_up_prospect(
    session: AsyncSession, prospect_id: uuid.UUID, *, campaign_status: OutreachCampaignStatus
) -> None:
    """Stage prompt Step 4: once every domain for a prospect has settled,
    move the prospect on. `ANALYZING` needs at least one genuine
    `COMPLETED` domain — `COMPLETED_PARTIAL` doesn't count, on the same
    "not a trustworthy result" reasoning that excludes it from hook
    selection (spec §5.2)."""
    prospect = await session.get(OutreachProspectRecord, prospect_id)
    if prospect is None or prospect.state != OutreachProspectState.SCANNING.value:
        return

    domains = (
        (
            await session.execute(
                select(OutreachDomainRecord).where(
                    OutreachDomainRecord.prospect_id == prospect_id
                )
            )
        )
        .scalars()
        .all()
    )
    unsettled_states = {
        OutreachDomainState.PENDING.value,
        OutreachDomainState.RUNNING.value,
        OutreachDomainState.RETRYING.value,
    }
    if any(d.state in unsettled_states for d in domains):
        return  # still work outstanding for this prospect

    completed = [d for d in domains if d.state == OutreachDomainState.COMPLETED.value]
    if completed:
        transition_prospect(
            prospect,
            OutreachProspectState.ANALYZING,
            campaign_status=campaign_status,
            reason=None,
        )
    else:
        partial = sum(1 for d in domains if d.state == OutreachDomainState.COMPLETED_PARTIAL.value)
        failed = sum(1 for d in domains if d.state == OutreachDomainState.FAILED.value)
        transition_prospect(
            prospect,
            OutreachProspectState.FAILED,
            campaign_status=campaign_status,
            reason=(
                f"no domain reached COMPLETED "
                f"({partial} completed_partial, {failed} failed, {len(domains)} total)"
            ),
        )
    await session.commit()


async def settle_running_domains(
    session: AsyncSession, redis: Redis, campaign: OutreachCampaignRecord
) -> int:
    """Reconciles every `RUNNING` domain for this campaign against its
    scan's real status. Runs for a `paused` campaign too, deliberately —
    pause blocks new claims, never work already in flight (CONTRACT.md
    §7.16)."""
    settings = get_settings()
    campaign_status = OutreachCampaignStatus(campaign.status)

    running = (
        (
            await session.execute(
                select(OutreachDomainRecord)
                .join(
                    OutreachProspectRecord,
                    OutreachProspectRecord.prospect_id == OutreachDomainRecord.prospect_id,
                )
                .where(
                    OutreachProspectRecord.campaign_id == campaign.campaign_id,
                    OutreachDomainRecord.state == OutreachDomainState.RUNNING.value,
                )
            )
        )
        .scalars()
        .all()
    )

    settled = 0
    for domain in running:
        prospect_id = domain.prospect_id
        did_settle = await _reconcile_running_domain(
            session, redis, domain, campaign_status=campaign_status, settings=settings
        )
        if did_settle:
            await session.commit()
            settled += 1
            await _maybe_roll_up_prospect(session, prospect_id, campaign_status=campaign_status)

    return settled


def _weak_prospect_filter(include_weak: bool) -> ColumnElement[bool]:
    if include_weak:
        return true()
    return or_(
        OutreachProspectRecord.icp_grade.is_(None),
        OutreachProspectRecord.icp_grade != "weak",
    )


async def claim_and_start_domains(
    session: AsyncSession,
    redis: Redis,
    arq_pool: ArqRedis,
    campaign: OutreachCampaignRecord,
    *,
    capacity: int,
) -> int:
    """One claim pass for one `running` campaign. Mirrors
    `app/scheduler.py`'s `claim_due_monitors` structurally: claim with
    `SELECT ... FOR UPDATE SKIP LOCKED` bounded by the currently available
    semaphore capacity, reserve each claimed slot before enqueueing, so a
    scan that outlives one tick is never claimed a second time and two
    ticks (or two worker processes) never claim the same domain."""
    if capacity <= 0:
        return 0

    settings = get_settings()
    campaign_status = OutreachCampaignStatus(campaign.status)
    now = datetime.now(UTC)
    retry_cutoff = now - timedelta(seconds=settings.outreach_retry_backoff_seconds)

    eligible = or_(
        OutreachDomainRecord.state == OutreachDomainState.PENDING.value,
        (OutreachDomainRecord.state == OutreachDomainState.RETRYING.value)
        & (OutreachDomainRecord.updated_at <= retry_cutoff),
        (OutreachDomainRecord.state == OutreachDomainState.COMPLETED_PARTIAL.value)
        & (OutreachDomainRecord.scan_attempts <= _COMPLETED_PARTIAL_RETRY_AT_ATTEMPTS)
        & (OutreachDomainRecord.updated_at <= retry_cutoff),
    )

    stmt = (
        select(OutreachDomainRecord)
        .join(
            OutreachProspectRecord,
            OutreachProspectRecord.prospect_id == OutreachDomainRecord.prospect_id,
        )
        .where(
            OutreachProspectRecord.campaign_id == campaign.campaign_id,
            eligible,
            _weak_prospect_filter(campaign.include_weak_prospects),
        )
        .order_by(OutreachDomainRecord.created_at.asc())
        .limit(capacity)
        .with_for_update(skip_locked=True, of=OutreachDomainRecord)
    )
    domains = (await session.execute(stmt)).scalars().all()
    if not domains:
        return 0

    claimed = 0
    for domain in domains:
        if domain.state == OutreachDomainState.COMPLETED_PARTIAL.value:
            # The one legal edge into RETRYING from COMPLETED_PARTIAL
            # (§7.16/§5.2) — its "one re-scan", not committed on its own so
            # this reads as one atomic claim, not two observable states.
            transition_domain(
                domain, OutreachDomainState.RETRYING, campaign_status=campaign_status, reason=None
            )

        domain.scan_attempts += 1
        transition_domain(
            domain, OutreachDomainState.RUNNING, campaign_status=campaign_status, reason=None
        )

        prospect = await session.get(OutreachProspectRecord, domain.prospect_id)
        if prospect is not None and prospect.state == OutreachProspectState.PENDING.value:
            transition_prospect(
                prospect,
                OutreachProspectState.SCANNING,
                campaign_status=campaign_status,
                reason=None,
            )

        scan_record = await _create_outreach_scan_record(session, domain.hostname)
        domain.scan_id = scan_record.scan_id
        await session.commit()

        await _reserve_capacity(redis, scan_record.scan_id, settings=settings)
        await arq_pool.enqueue_job("run_scan_job", str(scan_record.scan_id))
        claimed += 1

    return claimed


async def outreach_scan_tick(ctx: dict[str, Any]) -> None:
    """arq cron entrypoint (registered in app/worker.py), every
    `OUTREACH_SCAN_DELAY_SECONDS`. `ctx["redis"]` is arq's own
    worker-managed `ArqRedis` connection, reused for both the semaphore
    and enqueueing — same pattern as `app/scheduler.py`'s
    `run_scheduler_tick`, no second Redis connection opened just for
    this."""
    sessionmaker = get_sessionmaker()
    arq_pool: ArqRedis = ctx["redis"]
    settings = get_settings()

    async with sessionmaker() as session:
        campaigns = (
            (
                await session.execute(
                    select(OutreachCampaignRecord).where(
                        OutreachCampaignRecord.status.in_(
                            [
                                OutreachCampaignStatus.RUNNING.value,
                                OutreachCampaignStatus.PAUSED.value,
                            ]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )

        settled_total = 0
        for campaign in campaigns:
            # Pause blocks new claims below, never work already in flight —
            # settlement runs for both running and paused campaigns.
            settled_total += await settle_running_domains(session, arq_pool, campaign)

        claimed_total = 0
        for campaign in campaigns:
            if campaign.status != OutreachCampaignStatus.RUNNING.value:
                continue
            capacity = await _available_capacity(arq_pool, settings.outreach_max_concurrent_scans)
            if capacity <= 0:
                break  # global budget exhausted — no other running campaign can claim either
            claimed_total += await claim_and_start_domains(
                session, arq_pool, arq_pool, campaign, capacity=capacity
            )

    if settled_total or claimed_total:
        logger.info(
            "outreach_scan_tick",
            extra={"settled": settled_total, "claimed": claimed_total},
        )
