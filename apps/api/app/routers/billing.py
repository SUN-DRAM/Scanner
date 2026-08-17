"""GET /api/v1/billing/plans, POST /api/v1/billing/checkout,
POST /api/v1/billing/webhooks/{razorpay,stripe}, GET /api/v1/billing/subscription,
POST /api/v1/billing/cancel, GET /api/v1/billing/invoices (contract §7.11).

Billing is owner-only end to end (§7.6: "owner — everything, including
billing"... "admin — ...no billing") — every route here, including the
plain GETs, depends on `_require_owner`, not just the mutating ones the way
`routers/monitors.py`/`routers/orgs.py` scope role checks to writes only.
The two webhook routes are the deliberate exception: a payment provider has
no session cookie to send, so they authenticate by signature instead
(`app/billing/providers.py`), not `current_user`/`current_org`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers import BillingNotConfiguredError, SignatureVerificationError
from app.billing.service import (
    apply_checkout,
    cancel_org_subscription,
    get_priced_plans,
    process_webhook,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.deps import CurrentOrgContext, get_current_user, require_roles
from app.enums import BillingProvider, Currency, UserRole
from app.errors import ApiException, ErrorCode
from app.models import InvoiceRecord, SubscriptionRecord, UserRecord
from app.schemas import (
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingPlansResponse,
    Invoice,
    PaginatedList,
    Subscription,
)

router = APIRouter(prefix="/billing", tags=["billing"])

_MAX_PER_PAGE = 100  # contract §6.14
# Module-level singleton, not `Depends(require_roles(...))` inline at each
# call site — see routers/orgs.py's identical comment on the ruff B008
# tradeoff.
_require_owner = require_roles(UserRole.OWNER)


def _subscription_to_schema(record: SubscriptionRecord) -> Subscription:
    return Subscription(
        subscription_id=str(record.subscription_id),
        org_id=str(record.org_id),
        plan_code=record.plan_code,  # type: ignore[arg-type]
        provider=record.provider,  # type: ignore[arg-type]
        interval=record.interval,  # type: ignore[arg-type]
        currency=record.currency,  # type: ignore[arg-type]
        state=record.state,  # type: ignore[arg-type]
        current_period_start=record.current_period_start,
        current_period_end=record.current_period_end,
        cancel_at_period_end=record.cancel_at_period_end,
        provider_subscription_id=record.provider_subscription_id,
    )


def _invoice_to_schema(record: InvoiceRecord) -> Invoice:
    return Invoice(
        invoice_id=str(record.invoice_id),
        org_id=str(record.org_id),
        number=record.number,
        amount_minor=record.amount_minor,
        currency=record.currency,  # type: ignore[arg-type]
        state=record.state,  # type: ignore[arg-type]
        issued_at=record.issued_at,
        paid_at=record.paid_at,
        pdf_url=record.pdf_url,
        gstin=record.gstin,
        place_of_supply=record.place_of_supply,
    )


@router.get("/plans", response_model=BillingPlansResponse)
async def list_billing_plans(
    context: CurrentOrgContext = Depends(_require_owner),
) -> BillingPlansResponse:
    return BillingPlansResponse(plans=get_priced_plans(Currency(context.org.currency)))


@router.post("/checkout", response_model=BillingCheckoutResponse)
async def create_checkout(
    payload: BillingCheckoutRequest,
    context: CurrentOrgContext = Depends(_require_owner),
    current_user: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> BillingCheckoutResponse:
    return await apply_checkout(
        settings,
        org=context.org,
        user_email=current_user.email,
        plan_code=payload.plan_code,
        interval=payload.interval,
        gstin=payload.gstin,
        place_of_supply=payload.place_of_supply,
    )


async def _handle_webhook(
    request: Request, session: AsyncSession, settings: Settings, provider: BillingProvider
) -> dict[str, str]:
    raw_body = await request.body()
    try:
        await process_webhook(session, settings, provider, raw_body, dict(request.headers))
    except SignatureVerificationError as exc:
        raise ApiException(
            ErrorCode.WEBHOOK_INVALID_SIGNATURE, "Invalid webhook signature."
        ) from exc
    except BillingNotConfiguredError as exc:
        raise ApiException(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    return {"status": "ok"}


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return await _handle_webhook(request, session, settings, BillingProvider.RAZORPAY)


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return await _handle_webhook(request, session, settings, BillingProvider.STRIPE)


@router.get("/subscription", response_model=Subscription | None)
async def get_subscription(
    context: CurrentOrgContext = Depends(_require_owner),
    session: AsyncSession = Depends(get_session),
) -> Subscription | None:
    stmt = select(SubscriptionRecord).where(SubscriptionRecord.org_id == context.org.org_id)
    record = (await session.execute(stmt)).scalar_one_or_none()
    return _subscription_to_schema(record) if record is not None else None


@router.post("/cancel", response_model=Subscription)
async def cancel_subscription_endpoint(
    context: CurrentOrgContext = Depends(_require_owner),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Subscription:
    record = await cancel_org_subscription(session, settings, context.org)
    return _subscription_to_schema(record)


@router.get("/invoices", response_model=PaginatedList[Invoice])
async def list_invoices(
    context: CurrentOrgContext = Depends(_require_owner),
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_MAX_PER_PAGE),
) -> PaginatedList[Invoice]:
    base_stmt = select(InvoiceRecord).where(InvoiceRecord.org_id == context.org.org_id)
    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    stmt = (
        base_stmt.order_by(InvoiceRecord.issued_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [_invoice_to_schema(row) for row in rows]

    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )
