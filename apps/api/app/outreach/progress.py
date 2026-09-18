"""`GET .../scan-progress` (contract §7.16, v3.9/v3.10) — live progress and
Step 6's batch metrics, computed fresh on every call from `outreach_domains`
and the `scans` rows it references. Nothing here is stored; a batch
running for 40 minutes needs to be watchable without SSH, not reported on
after the fact.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OutreachCampaignStatus, OutreachDomainState
from app.models import (
    OutreachCampaignRecord,
    OutreachDomainRecord,
    OutreachProspectRecord,
    ScanRecord,
)
from app.scan_compat import parse_stored_scan
from app.schemas import OutreachRecentOutcome, OutreachScanMetrics, OutreachScanProgress

_RECENT_OUTCOMES_LIMIT = 20

# "Two settled domains out of 150 is not a basis for a completion time" —
# human sign-off, same principle as the partial-scan score ceiling (§9 Step
# 4b, v3.4): don't show a precise number the data doesn't support. Held
# null below this many settled domains, regardless of how long the batch
# has been running.
MIN_SETTLED_FOR_ESTIMATE = 10

_UNSETTLED_STATES = {
    OutreachDomainState.PENDING.value,
    OutreachDomainState.RUNNING.value,
    OutreachDomainState.RETRYING.value,
}
_TERMINAL_STATES = {
    OutreachDomainState.COMPLETED.value,
    OutreachDomainState.COMPLETED_PARTIAL.value,
    OutreachDomainState.FAILED.value,
}


def _percentile(sorted_values: list[int], fraction: float) -> int | None:
    """Linear-interpolation percentile (numpy's default) over an
    already-sorted list. `None` for an empty input rather than a
    division-by-zero guess."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = fraction * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return round(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


async def build_scan_progress(
    session: AsyncSession, campaign: OutreachCampaignRecord
) -> OutreachScanProgress:
    domains = (
        (
            await session.execute(
                select(OutreachDomainRecord).where(
                    OutreachDomainRecord.prospect_id.in_(
                        select(OutreachProspectRecord.prospect_id).where(
                            OutreachProspectRecord.campaign_id == campaign.campaign_id
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    domain_state_counts = dict.fromkeys(OutreachDomainState, 0)
    for domain in domains:
        domain_state_counts[OutreachDomainState(domain.state)] += 1

    in_flight = domain_state_counts[OutreachDomainState.RUNNING]

    settled_updated_ats = [d.updated_at for d in domains if d.state in _TERMINAL_STATES]
    unsettled_present = any(d.state in _UNSETTLED_STATES for d in domains)
    touched_updated_ats = [
        d.updated_at for d in domains if d.state != OutreachDomainState.PENDING.value
    ]
    started_at = min(touched_updated_ats) if touched_updated_ats else None

    now = datetime.now(UTC)
    settled_count = len(settled_updated_ats)
    remaining = sum(1 for d in domains if d.state in _UNSETTLED_STATES)

    estimated_completion_at = None
    if started_at is not None and settled_count >= MIN_SETTLED_FOR_ESTIMATE and remaining > 0:
        elapsed = (now - started_at).total_seconds()
        pace_seconds_per_domain = elapsed / settled_count
        estimated_completion_at = now + timedelta(seconds=remaining * pace_seconds_per_domain)

    total_wall_time_ms = None
    if started_at is not None:
        last_settled = max(settled_updated_ats) if settled_updated_ats else now
        end = now if unsettled_present else last_settled
        total_wall_time_ms = int((end - started_at).total_seconds() * 1000)

    recent = sorted(
        (d for d in domains if d.state in _TERMINAL_STATES),
        key=lambda d: d.updated_at,
        reverse=True,
    )[:_RECENT_OUTCOMES_LIMIT]
    prospects_by_id: dict[uuid.UUID, OutreachProspectRecord] = {}
    if recent:
        prospect_ids = {d.prospect_id for d in recent}
        rows = (
            await session.execute(
                select(OutreachProspectRecord).where(
                    OutreachProspectRecord.prospect_id.in_(prospect_ids)
                )
            )
        ).scalars()
        prospects_by_id = {p.prospect_id: p for p in rows}

    recent_outcomes = [
        OutreachRecentOutcome(
            domain_id=str(d.domain_id),
            hostname=d.hostname,
            prospect_id=str(d.prospect_id),
            agency_name=prospects_by_id[d.prospect_id].agency_name
            if d.prospect_id in prospects_by_id
            else "",
            state=OutreachDomainState(d.state),
            scan_error=d.scan_error,
            settled_at=d.updated_at,
        )
        for d in recent
    ]

    metrics = await _build_metrics(session, domains, total_wall_time_ms=total_wall_time_ms)

    return OutreachScanProgress(
        campaign_id=str(campaign.campaign_id),
        campaign_status=OutreachCampaignStatus(campaign.status),
        domain_state_counts=domain_state_counts,
        in_flight=in_flight,
        started_at=started_at,
        estimated_completion_at=estimated_completion_at,
        recent_outcomes=recent_outcomes,
        metrics=metrics,
    )


async def _build_metrics(
    session: AsyncSession,
    domains: Sequence[OutreachDomainRecord],
    *,
    total_wall_time_ms: int | None,
) -> OutreachScanMetrics:
    total = len(domains)
    completed = sum(1 for d in domains if d.state == OutreachDomainState.COMPLETED.value)
    completed_partial_domains = [
        d for d in domains if d.state == OutreachDomainState.COMPLETED_PARTIAL.value
    ]
    failed_domains = [d for d in domains if d.state == OutreachDomainState.FAILED.value]

    clean_rate = round(completed / total, 4) if total > 0 else None

    completed_partial_by_module_error: dict[str, int] = {}
    for domain in completed_partial_domains:
        if domain.scan_id is None:
            continue
        scan = await session.get(ScanRecord, domain.scan_id)
        if scan is None or scan.result is None:
            continue
        parsed = parse_stored_scan(scan.result)
        for name in parsed.incomplete_modules or []:
            result = getattr(parsed.modules, name.value, None)
            if result is not None and result.error is not None:
                code = result.error.code.value
                completed_partial_by_module_error[code] = (
                    completed_partial_by_module_error.get(code, 0) + 1
                )

    failed_by_reason: dict[str, int] = {}
    for domain in failed_domains:
        reason = domain.scan_error or "unknown"
        failed_by_reason[reason] = failed_by_reason.get(reason, 0) + 1

    scan_ids = [d.scan_id for d in domains if d.scan_id is not None]
    durations: list[int] = []
    if scan_ids:
        rows = await session.execute(
            select(ScanRecord.duration_ms).where(
                ScanRecord.scan_id.in_(scan_ids), ScanRecord.duration_ms.is_not(None)
            )
        )
        durations = sorted(d for (d,) in rows.all())

    _rescued_states = (
        OutreachDomainState.COMPLETED.value,
        OutreachDomainState.COMPLETED_PARTIAL.value,
    )
    retried_and_rescued_count = sum(
        1 for d in domains if d.scan_attempts > 1 and d.state in _rescued_states
    )

    return OutreachScanMetrics(
        clean_rate=clean_rate,
        completed_partial_count=len(completed_partial_domains),
        completed_partial_by_module_error=completed_partial_by_module_error,
        failed_count=len(failed_domains),
        failed_by_reason=failed_by_reason,
        median_scan_duration_ms=_percentile(durations, 0.5),
        p95_scan_duration_ms=_percentile(durations, 0.95),
        retried_and_rescued_count=retried_and_rescued_count,
        total_wall_time_ms=total_wall_time_ms,
    )
