"""Plan pricing and limits — contract §5.1, single source of truth. Every
quota check, the pricing page (Step 7), and checkout (Step 6) read prices
and limits from here; never a hardcoded number in a handler or a component.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.enums import BillingInterval, Currency, PlanCode


@dataclass(frozen=True)
class PlanDefinition:
    code: PlanCode
    inr_minor_monthly: int  # paise
    usd_minor_monthly: int  # cents
    # `None` on secure/compliance: those rows exist so PlanCode -> PlanDefinition
    # stays total, but no Phase 2 code path can ever assign an org to either
    # plan (checkout is a "contact us" path, §5.1) — inventing a numeric limit
    # for them would be a guess this contract's accuracy rule (CLAUDE.md rule 7)
    # forbids, so their operational fields are `None` ("not enforced here").
    hostname_limit: int | None
    scan_interval_hours: int | None
    alert_lead_days: tuple[int, ...]
    member_limit: int | None
    purchasable: bool


ANNUAL_DISCOUNT_MULTIPLIER = 0.7  # §5.1: annual = monthly x 12 x 0.7 (30% off)

PLANS: dict[PlanCode, PlanDefinition] = {
    PlanCode.FREE: PlanDefinition(
        code=PlanCode.FREE,
        inr_minor_monthly=0,
        usd_minor_monthly=0,
        hostname_limit=3,
        scan_interval_hours=24,
        alert_lead_days=(14, 3),
        member_limit=1,
        purchasable=True,
    ),
    PlanCode.WATCH: PlanDefinition(
        code=PlanCode.WATCH,
        inr_minor_monthly=99_900,
        usd_minor_monthly=2_900,
        hostname_limit=25,
        scan_interval_hours=6,
        alert_lead_days=(60, 30, 14, 7, 3, 1),
        member_limit=3,
        purchasable=True,
    ),
    PlanCode.WATCH_PRO: PlanDefinition(
        code=PlanCode.WATCH_PRO,
        inr_minor_monthly=299_900,
        usd_minor_monthly=7_900,
        hostname_limit=100,
        scan_interval_hours=6,
        alert_lead_days=(60, 30, 14, 7, 3, 1),
        member_limit=10,
        purchasable=True,
    ),
    PlanCode.SECURE: PlanDefinition(
        code=PlanCode.SECURE,
        inr_minor_monthly=0,
        usd_minor_monthly=0,
        hostname_limit=None,
        scan_interval_hours=None,
        alert_lead_days=(),
        member_limit=None,
        purchasable=False,
    ),
    PlanCode.COMPLIANCE: PlanDefinition(
        code=PlanCode.COMPLIANCE,
        inr_minor_monthly=0,
        usd_minor_monthly=0,
        hostname_limit=None,
        scan_interval_hours=None,
        alert_lead_days=(),
        member_limit=None,
        purchasable=False,
    ),
}

# Ordering among purchasable plans only — feeds QUOTA_EXCEEDED's `upgrade_to`
# (§7.8). `watch_pro` has no next step in Phase 2: secure/compliance aren't
# purchasable, so there is nothing to suggest.
_NEXT_PURCHASABLE_PLAN: dict[PlanCode, PlanCode | None] = {
    PlanCode.FREE: PlanCode.WATCH,
    PlanCode.WATCH: PlanCode.WATCH_PRO,
    PlanCode.WATCH_PRO: None,
}


def get_plan(code: PlanCode) -> PlanDefinition:
    return PLANS[code]


def next_purchasable_plan(code: PlanCode) -> PlanCode | None:
    return _NEXT_PURCHASABLE_PLAN.get(code)


def priced_amount_minor(
    plan: PlanDefinition, currency: Currency, interval: BillingInterval
) -> int | None:
    """§5.1/§7.11: the amount one invoice for `plan` charges in `currency`,
    for `interval`. `None` for a non-purchasable plan (secure/compliance) —
    never `0`, which would misread as "free" rather than "not sold here"
    (§Step 6: "contact us" at checkout, no numeric price exists to return).
    Annual is `monthly x 12 x ANNUAL_DISCOUNT_MULTIPLIER` (§5.1), rounded to
    the nearest minor unit — exact for every plan/currency combination in
    the table today, never a guess."""
    if not plan.purchasable:
        return None
    monthly = plan.inr_minor_monthly if currency == Currency.INR else plan.usd_minor_monthly
    if interval == BillingInterval.ANNUAL:
        return round(monthly * 12 * ANNUAL_DISCOUNT_MULTIPLIER)
    return monthly
