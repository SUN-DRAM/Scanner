"""Billing business logic (contract §7.11): pricing, checkout, webhook
processing (idempotent, provider-agnostic), cancellation, the downgrade
quota-block, and the period-end expiry sweep. `routers/billing.py` and
`app/worker.py` are the only callers — no HTTP concerns live here, the same
split `app/monitors.py` and `app/alerts.py` already use.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers import (
    BillingNotConfiguredError,
    ProviderRequestError,
    SignatureVerificationError,
    WebhookEvent,
    get_billing_provider,
    get_billing_provider_by_name,
)
from app.config import Settings
from app.enums import (
    BillingInterval,
    BillingProvider,
    Currency,
    InvoiceState,
    MonitorState,
    PlanCode,
    SubscriptionState,
)
from app.errors import ApiException, ErrorCode
from app.models import (
    BillingEventRecord,
    InvoiceRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    SubscriptionRecord,
)
from app.monitors import QUOTA_COUNTED_STATES
from app.plans import PLANS, get_plan, priced_amount_minor
from app.schemas import BillingCheckoutResponse, PricedPlan

logger = logging.getLogger("app.billing.service")

# Re-exported for SignatureVerificationError/BillingNotConfiguredError so
# routers/billing.py has one import surface for this module's exceptions.
__all__ = [
    "BillingNotConfiguredError",
    "SignatureVerificationError",
    "apply_checkout",
    "apply_plan_downgrade",
    "cancel_org_subscription",
    "expire_due_cancellations",
    "get_priced_plans",
    "process_webhook",
]


# --- GET /billing/plans ---


def get_priced_plans(currency: Currency) -> list[PricedPlan]:
    """§5.1's table, priced in `currency` — every `PlanCode`, always, in the
    table's own order (§7.11: secure/compliance appear with both amount
    fields `null`, not omitted, so the pricing page needs no second call)."""
    return [
        PricedPlan(
            plan_code=plan.code,
            purchasable=plan.purchasable,
            currency=currency,
            monthly_amount_minor=priced_amount_minor(plan, currency, BillingInterval.MONTHLY),
            annual_amount_minor=priced_amount_minor(plan, currency, BillingInterval.ANNUAL),
            hostname_limit=plan.hostname_limit,
            scan_interval_hours=plan.scan_interval_hours,
            alert_lead_days=list(plan.alert_lead_days),
            member_limit=plan.member_limit,
        )
        for plan in PLANS.values()
    ]


# --- POST /billing/checkout ---


async def apply_checkout(
    settings: Settings,
    *,
    org: OrganisationRecord,
    user_email: str,
    plan_code: PlanCode,
    interval: BillingInterval,
    gstin: str | None,
    place_of_supply: str | None,
) -> BillingCheckoutResponse:
    """Never writes a `subscriptions` row — only asks the provider to start
    one. "Webhooks are the source of truth for subscription state, not the
    checkout redirect" (§Step 6) holds structurally this way, not just as a
    stated intention: `GET /billing/subscription` stays `null` until
    `process_webhook` below actually confirms something."""
    plan = get_plan(plan_code)
    if not plan.purchasable:
        return BillingCheckoutResponse(checkout_url=None, provider=None, contact_us=True)

    currency = Currency(org.currency)
    amount_minor = priced_amount_minor(plan, currency, interval)
    # plan.purchasable is True, so this is never None — asserted, not
    # guessed (CLAUDE.md rule 7).
    assert amount_minor is not None

    try:
        client = get_billing_provider(settings, currency)
    except BillingNotConfiguredError as exc:
        raise ApiException(ErrorCode.INTERNAL_ERROR, str(exc)) from exc

    try:
        checkout_session = await client.create_checkout_session(
            org_id=str(org.org_id),
            plan_code=plan_code.value,
            interval=interval,
            amount_minor=amount_minor,
            currency=currency,
            customer_email=user_email,
            success_url=f"{settings.public_base_url}/app/billing?checkout=success",
            cancel_url=f"{settings.public_base_url}/app/billing?checkout=cancelled",
            gstin=gstin,
            place_of_supply=place_of_supply,
        )
    except ProviderRequestError as exc:
        logger.error("billing_checkout_provider_error", extra={"org_id": str(org.org_id)})
        raise ApiException(
            ErrorCode.INTERNAL_ERROR, "Could not start checkout. Try again shortly."
        ) from exc

    return BillingCheckoutResponse(
        checkout_url=checkout_session.checkout_url, provider=client.provider, contact_us=False
    )


# --- POST /billing/webhooks/{razorpay,stripe} ---


async def _mark_event_seen(session: AsyncSession, provider: BillingProvider, event_id: str) -> bool:
    """Returns True if `(provider, event_id)` was already recorded (a
    replayed delivery — skip it), False if this call just recorded it for
    the first time. Insert-then-catch, not select-then-insert: two
    concurrent deliveries of the same retried event race the unique
    constraint, not a check that itself has a gap (same pattern as
    `app.monitors.create_monitor`'s `DUPLICATE_HOSTNAME` handling)."""
    session.add(BillingEventRecord(id=uuid.uuid4(), provider=provider.value, event_id=event_id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return True
    return False


async def _get_or_create_subscription(
    session: AsyncSession, org: OrganisationRecord, event: WebhookEvent, provider: BillingProvider
) -> SubscriptionRecord:
    stmt = select(SubscriptionRecord).where(SubscriptionRecord.org_id == org.org_id)
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is not None:
        return record

    now = datetime.now(UTC)
    record = SubscriptionRecord(
        subscription_id=uuid.uuid4(),
        org_id=org.org_id,
        plan_code=event.plan_code or org.plan_code,
        provider=provider.value,
        interval=event.interval or BillingInterval.MONTHLY.value,
        currency=org.currency,
        state=SubscriptionState.TRIALING.value,
        current_period_start=now,
        current_period_end=now,
        cancel_at_period_end=False,
        provider_subscription_id=event.provider_subscription_id,
    )
    session.add(record)
    return record


async def _apply_subscription_event(
    session: AsyncSession, org: OrganisationRecord, event: WebhookEvent, provider: BillingProvider
) -> None:
    record = await _get_or_create_subscription(session, org, event, provider)

    if event.provider_subscription_id:
        record.provider_subscription_id = event.provider_subscription_id
    if event.plan_code:
        record.plan_code = event.plan_code
    if event.interval:
        record.interval = event.interval
    if event.current_period_start is not None:
        record.current_period_start = datetime.fromtimestamp(event.current_period_start, tz=UTC)
    if event.current_period_end is not None:
        record.current_period_end = datetime.fromtimestamp(event.current_period_end, tz=UTC)
    if event.cancel_at_period_end is not None:
        record.cancel_at_period_end = event.cancel_at_period_end

    if event.event_type == "subscription.active":
        record.state = SubscriptionState.ACTIVE.value
        if event.plan_code:
            org.plan_code = event.plan_code
    elif event.event_type == "subscription.past_due":
        record.state = SubscriptionState.PAST_DUE.value


async def _apply_cancellation(session: AsyncSession, org: OrganisationRecord) -> None:
    stmt = select(SubscriptionRecord).where(SubscriptionRecord.org_id == org.org_id)
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is not None:
        record.state = SubscriptionState.CANCELLED.value
        record.cancel_at_period_end = False  # already happened — nothing left to defer
    org.plan_code = PlanCode.FREE.value
    await apply_plan_downgrade(session, org, PlanCode.FREE)


async def _generate_invoice_number(session: AsyncSession) -> str:
    year = datetime.now(UTC).year
    prefix = f"INV-{year}-"
    stmt = select(InvoiceRecord.number).where(InvoiceRecord.number.like(f"{prefix}%"))
    existing = (await session.execute(stmt)).scalars().all()
    return f"{prefix}{len(existing) + 1:06d}"


async def _record_invoice(
    session: AsyncSession, org: OrganisationRecord, event: WebhookEvent
) -> None:
    if event.charge_amount_minor is None:
        return
    now = datetime.now(UTC)
    for _ in range(5):  # collision retry, same shape as scans.public_slug's
        number = await _generate_invoice_number(session)
        session.add(
            InvoiceRecord(
                invoice_id=uuid.uuid4(),
                org_id=org.org_id,
                number=number,
                amount_minor=event.charge_amount_minor,
                currency=event.charge_currency or org.currency,
                state=InvoiceState.PAID.value,
                issued_at=now,
                paid_at=now,
                pdf_url=None,
                gstin=event.gstin,
                place_of_supply=event.place_of_supply,
            )
        )
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        return
    raise ApiException(ErrorCode.INTERNAL_ERROR, "Could not allocate a unique invoice number.")


async def process_webhook(
    session: AsyncSession,
    settings: Settings,
    provider: BillingProvider,
    raw_body: bytes,
    headers: dict[str, str],
) -> None:
    try:
        client = get_billing_provider_by_name(settings, provider)
    except BillingNotConfiguredError as exc:
        raise ApiException(ErrorCode.INTERNAL_ERROR, str(exc)) from exc

    event = client.verify_and_parse_webhook(raw_body=raw_body, headers=headers)

    if await _mark_event_seen(session, provider, event.event_id):
        logger.info(
            "billing_webhook_duplicate",
            extra={"provider": provider.value, "event_id": event.event_id},
        )
        return

    if event.org_id is None:
        logger.warning(
            "billing_webhook_unattributed",
            extra={"provider": provider.value, "raw_type": event.raw_type},
        )
        return
    try:
        org_uuid = uuid.UUID(event.org_id)
    except ValueError:
        logger.warning("billing_webhook_bad_org_id", extra={"provider": provider.value})
        return

    org = await session.get(OrganisationRecord, org_uuid)
    if org is None:
        return

    if event.event_type in (
        "subscription.checkout_completed",
        "subscription.active",
        "subscription.past_due",
    ):
        await _apply_subscription_event(session, org, event, provider)
    elif event.event_type == "subscription.cancelled":
        await _apply_cancellation(session, org)
    elif event.event_type == "subscription.charged":
        await _record_invoice(session, org, event)
    else:
        logger.info(
            "billing_webhook_ignored",
            extra={"provider": provider.value, "raw_type": event.raw_type},
        )

    await session.commit()


# --- POST /billing/cancel ---

_CANCELLABLE_STATES = frozenset(
    {
        SubscriptionState.TRIALING.value,
        SubscriptionState.ACTIVE.value,
        SubscriptionState.PAST_DUE.value,
    }
)


async def cancel_org_subscription(
    session: AsyncSession, settings: Settings, org: OrganisationRecord
) -> SubscriptionRecord:
    stmt = select(SubscriptionRecord).where(SubscriptionRecord.org_id == org.org_id)
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None or record.state not in _CANCELLABLE_STATES:
        raise ApiException(ErrorCode.NOT_FOUND, "No active subscription to cancel.")

    if record.cancel_at_period_end:
        return record  # idempotent — already cancelling, don't re-call the provider

    if record.provider_subscription_id is None:
        raise ApiException(
            ErrorCode.INTERNAL_ERROR, "This subscription has no provider reference to cancel."
        )
    try:
        client = get_billing_provider_by_name(settings, BillingProvider(record.provider))
        await client.cancel_subscription(record.provider_subscription_id)
    except BillingNotConfiguredError as exc:
        raise ApiException(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    except ProviderRequestError as exc:
        raise ApiException(
            ErrorCode.INTERNAL_ERROR,
            "Could not cancel with the payment provider. Try again shortly.",
        ) from exc

    record.cancel_at_period_end = True
    await session.commit()
    await session.refresh(record)
    return record


# --- §Step 3's downgrade rule, triggered by cancellation (above) and the
# period-end expiry sweep (below) ---


async def apply_plan_downgrade(
    session: AsyncSession, org: OrganisationRecord, new_plan_code: PlanCode
) -> None:
    """§7.8: "On downgrade... never delete hostnames. Set the excess to
    quota_blocked, oldest-first by created_at." Read literally: iterating
    `created_at` ascending, the oldest rows are the ones blocked first (the
    newest stay active) — a deterministic ordering CONTRACT.md's §14 v2.5
    amendment note flags as an interpretation, not a value judgement about
    which hostnames matter more."""
    plan = get_plan(new_plan_code)
    if plan.hostname_limit is None:
        return

    stmt = (
        select(MonitoredHostnameRecord)
        .where(
            MonitoredHostnameRecord.org_id == org.org_id,
            MonitoredHostnameRecord.state.in_(QUOTA_COUNTED_STATES),
        )
        .order_by(MonitoredHostnameRecord.created_at.asc())
    )
    monitors = (await session.execute(stmt)).scalars().all()
    excess = len(monitors) - plan.hostname_limit
    if excess <= 0:
        return
    for monitor in monitors[:excess]:
        monitor.state = MonitorState.QUOTA_BLOCKED.value
        monitor.next_scan_at = None


async def expire_due_cancellations(session: AsyncSession) -> int:
    """arq cron (`app/worker.py`, 5-minute cadence): a `cancel_at_period_end`
    subscription whose `current_period_end` has actually passed reverts its
    org to `free` and applies the same downgrade quota-block. Returns how
    many were expired, for logging."""
    now = datetime.now(UTC)
    stmt = select(SubscriptionRecord).where(
        SubscriptionRecord.cancel_at_period_end.is_(True),
        SubscriptionRecord.state.in_(_CANCELLABLE_STATES),
        SubscriptionRecord.current_period_end <= now,
    )
    records = (await session.execute(stmt)).scalars().all()
    if not records:
        return 0

    expired = 0
    for record in records:
        # CANCELLED, not EXPIRED: this is the same terminal state a
        # provider's own cancellation webhook would have set had it arrived
        # first (§7.11) — this sweep only exists to catch the case where the
        # period simply elapses with no such event, not a distinct outcome.
        record.state = SubscriptionState.CANCELLED.value
        record.cancel_at_period_end = False
        org = await session.get(OrganisationRecord, record.org_id)
        if org is not None:
            org.plan_code = PlanCode.FREE.value
            await apply_plan_downgrade(session, org, PlanCode.FREE)
        expired += 1

    await session.commit()
    return expired
