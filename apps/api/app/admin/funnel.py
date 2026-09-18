"""`GET /api/v1/admin/funnel` (contract §7.13) — the Phase 1 acquisition
path over the last 30 days, since that is what cold outreach feeds.

Documented approximations (every value is still a real query, contract
rule 7): a scan counts as **logged-in** when `scans.monitor_id` is non-null
(it ran on behalf of an account's monitor), **anonymous** otherwise.
Prospect scans (§11) are excluded via `NOT EXISTS` against
`prospect_scans` **and**, since the outreach orchestrator Stage 2 (v3.9)
started populating it, `outreach_domains.scan_id` — two separate prospect-
scan producers, both excluded, neither replacing the other (§7.15's own
boundary note). Flagged as a forward TODO at v3.6, closed here now that
Stage 2 actually links a `scans` row to an `outreach_domains` row for the
first time; before this fix, an outreach batch's scans would have quietly
inflated the anonymous-scan count exactly like a real acquisition-funnel
signal, weeks before anyone thought to check why scan volume had jumped.
Activation / paid rates are windowed org counts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SubscriptionState
from app.models import (
    MonitoredHostnameRecord,
    OrganisationRecord,
    OutreachDomainRecord,
    ProspectScanRecord,
    ScanRecord,
    SubscriptionRecord,
    WaitlistSignupRecord,
)
from app.schemas import (
    AdminFunnelPoint,
    AdminFunnelRates,
    AdminFunnelReport,
    AdminFunnelSeries,
)

_FUNNEL_DAYS = 30

_PAYING_STATES = (
    SubscriptionState.ACTIVE.value,
    SubscriptionState.TRIALING.value,
    SubscriptionState.PAST_DUE.value,
)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


async def build_funnel_report(session: AsyncSession) -> AdminFunnelReport:
    now = datetime.now(UTC)
    start_date = now.date() - timedelta(days=_FUNNEL_DAYS - 1)
    window_start = datetime.combine(start_date, time.min, tzinfo=UTC)
    days = [start_date + timedelta(days=offset) for offset in range(_FUNNEL_DAYS)]

    scan_day = func.date(func.timezone("UTC", ScanRecord.created_at))
    is_prospect_scan = (
        select(ProspectScanRecord.id)
        .where(ProspectScanRecord.scan_id == ScanRecord.scan_id)
        .exists()
    )
    # v3.9: the outreach orchestrator's own prospect-scan producer, excluded
    # alongside (not instead of) prospect_scans above — see this module's
    # docstring.
    is_outreach_scan = (
        select(OutreachDomainRecord.domain_id)
        .where(OutreachDomainRecord.scan_id == ScanRecord.scan_id)
        .exists()
    )
    scan_mappings = (
        (
            await session.execute(
                select(
                    scan_day.label("day"),
                    func.count().label("total"),
                    func.count().filter(ScanRecord.monitor_id.is_(None)).label("anonymous"),
                    func.count().filter(ScanRecord.monitor_id.is_not(None)).label("logged_in"),
                    func.count(distinct(ScanRecord.hostname)).label("unique_hostnames"),
                )
                .where(
                    ScanRecord.created_at >= window_start,
                    ~is_prospect_scan,
                    ~is_outreach_scan,
                )
                .group_by(scan_day)
            )
        )
        .mappings()
        .all()
    )
    scans_by_day: dict[date, dict[str, int]] = {
        row["day"]: {
            "total": int(row["total"]),
            "anonymous": int(row["anonymous"]),
            "logged_in": int(row["logged_in"]),
            "unique_hostnames": int(row["unique_hostnames"]),
        }
        for row in scan_mappings
    }

    waitlist_day = func.date(func.timezone("UTC", WaitlistSignupRecord.created_at))
    waitlist_mappings = (
        (
            await session.execute(
                select(waitlist_day.label("day"), func.count().label("signups"))
                .where(WaitlistSignupRecord.created_at >= window_start)
                .group_by(waitlist_day)
            )
        )
        .mappings()
        .all()
    )
    waitlist_by_day: dict[date, int] = {
        row["day"]: int(row["signups"]) for row in waitlist_mappings
    }

    def _series(getter: Callable[[date], int]) -> list[AdminFunnelPoint]:
        return [AdminFunnelPoint(date=day, value=getter(day)) for day in days]

    def _scan_metric(key: str) -> Callable[[date], int]:
        return lambda day: scans_by_day[day][key] if day in scans_by_day else 0

    series = AdminFunnelSeries(
        scans_total=_series(_scan_metric("total")),
        scans_anonymous=_series(_scan_metric("anonymous")),
        scans_logged_in=_series(_scan_metric("logged_in")),
        unique_hostnames=_series(_scan_metric("unique_hostnames")),
        waitlist_signups=_series(lambda day: waitlist_by_day.get(day, 0)),
    )

    total_scans = sum(point.value for point in series.scans_total)
    total_waitlist = sum(point.value for point in series.waitlist_signups)

    orgs_created = int(
        (
            await session.execute(
                select(func.count())
                .select_from(OrganisationRecord)
                .where(OrganisationRecord.created_at >= window_start)
            )
        ).scalar_one()
    )
    has_monitor = (
        select(MonitoredHostnameRecord.monitor_id)
        .where(MonitoredHostnameRecord.org_id == OrganisationRecord.org_id)
        .exists()
    )
    orgs_activated = int(
        (
            await session.execute(
                select(func.count())
                .select_from(OrganisationRecord)
                .where(OrganisationRecord.created_at >= window_start, has_monitor)
            )
        ).scalar_one()
    )
    has_active_subscription = (
        select(SubscriptionRecord.subscription_id)
        .where(
            SubscriptionRecord.org_id == OrganisationRecord.org_id,
            SubscriptionRecord.state.in_(_PAYING_STATES),
        )
        .exists()
    )
    orgs_paid = int(
        (
            await session.execute(
                select(func.count())
                .select_from(OrganisationRecord)
                .where(OrganisationRecord.created_at >= window_start, has_active_subscription)
            )
        ).scalar_one()
    )

    rates = AdminFunnelRates(
        scan_to_waitlist=_rate(total_waitlist, total_scans),
        waitlist_to_account=_rate(orgs_created, total_waitlist),
        account_to_activation=_rate(orgs_activated, orgs_created),
        account_to_paid=_rate(orgs_paid, orgs_created),
    )

    return AdminFunnelReport(generated_at=now, days=_FUNNEL_DAYS, series=series, rates=rates)
