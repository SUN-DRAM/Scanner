"""HTTP-level tests for /api/v1/billing/* (contract §7.11): owner-only RBAC
on every route including the plain GETs, the checkout/contact-us split,
webhook signature verification + idempotency end to end through the real
router, cancel, and the downgrade quota-block.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers import CheckoutSession
from app.billing.service import apply_plan_downgrade
from app.config import Settings, get_settings
from app.db import get_session
from app.enums import BillingProvider, MonitorState, PlanCode
from app.main import app
from app.models import MonitoredHostnameRecord, OrganisationRecord, SubscriptionRecord
from app.notify.email import get_email_sender
from app.ratelimit import hash_for_bucket
from app.redis_client import get_redis_client

_CODE_PATTERN = re.compile(r"\b(\d{6})\b")
_WEBHOOK_SECRET = "test-webhook-secret"


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


def _extract_code(sender: FakeEmailSender) -> str:
    match = _CODE_PATTERN.search(sender.sent[-1]["text"])
    assert match is not None
    return match.group(1)


def _test_settings() -> Settings:
    return Settings(
        SESSION_SECRET="test-secret",
        CORS_ORIGINS="http://test",
        RAZORPAY_KEY_ID="rzp_test_id",
        RAZORPAY_KEY_SECRET="rzp_test_secret",
        RAZORPAY_WEBHOOK_SECRET=_WEBHOOK_SECRET,
        STRIPE_SECRET_KEY="sk_test_x",
        STRIPE_WEBHOOK_SECRET=_WEBHOOK_SECRET,
    )


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def _wired_app(
    db_session: AsyncSession, fake_email_sender: FakeEmailSender, redis_client: Redis
) -> Iterator[None]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_settings] = _test_settings
    app.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def _reset_otp_ip_rate_limit(redis_client: Redis) -> AsyncGenerator[None]:
    yield
    await redis_client.delete(f"ratelimit:otp:ip:{hash_for_bucket('127.0.0.1')}")


def _random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


async def _new_client(_wired_app: None) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _login(client: AsyncClient, fake_email_sender: FakeEmailSender, email: str) -> dict:
    await client.post("/api/v1/auth/otp/request", json={"email": email})
    code = _extract_code(fake_email_sender)
    response = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
async def owner_client(
    _wired_app: None, fake_email_sender: FakeEmailSender, redis_client: Redis
) -> AsyncGenerator[AsyncClient]:
    client = await _new_client(_wired_app)
    await _login(client, fake_email_sender, _random_email())
    yield client
    await client.aclose()


async def _invite_and_login_member(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> AsyncClient:
    member_email = _random_email()
    await owner_client.post(
        "/api/v1/orgs/current/members", json={"email": member_email, "role": "member"}
    )
    member_client = await _new_client(_wired_app)
    await _login(member_client, fake_email_sender, member_email)
    return member_client


# --- RBAC: owner-only, including the plain GETs ---


@pytest.mark.asyncio
async def test_member_cannot_reach_any_billing_route(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> None:
    member_client = await _invite_and_login_member(owner_client, _wired_app, fake_email_sender)
    try:
        plans_response = await member_client.get("/api/v1/billing/plans")
        assert plans_response.status_code == 403
        assert plans_response.json()["error"]["code"] == "FORBIDDEN"

        subscription_response = await member_client.get("/api/v1/billing/subscription")
        assert subscription_response.status_code == 403

        invoices_response = await member_client.get("/api/v1/billing/invoices")
        assert invoices_response.status_code == 403

        checkout_response = await member_client.post(
            "/api/v1/billing/checkout", json={"plan_code": "watch", "interval": "monthly"}
        )
        assert checkout_response.status_code == 403

        cancel_response = await member_client.post("/api/v1/billing/cancel")
        assert cancel_response.status_code == 403
    finally:
        await member_client.aclose()


@pytest.mark.asyncio
async def test_admin_cannot_reach_billing_either(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> None:
    admin_email = _random_email()
    await owner_client.post(
        "/api/v1/orgs/current/members", json={"email": admin_email, "role": "admin"}
    )
    admin_client = await _new_client(_wired_app)
    try:
        await _login(admin_client, fake_email_sender, admin_email)
        response = await admin_client.get("/api/v1/billing/plans")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
    finally:
        await admin_client.aclose()


# --- GET /billing/plans ---


@pytest.mark.asyncio
async def test_plans_are_priced_in_the_orgs_currency(owner_client: AsyncClient) -> None:
    response = await owner_client.get("/api/v1/billing/plans")
    assert response.status_code == 200
    plans = {row["plan_code"]: row for row in response.json()["plans"]}

    assert plans["watch"]["currency"] == "INR"  # personal orgs default to INR
    assert plans["watch"]["monthly_amount_minor"] == 99_900
    assert plans["watch"]["annual_amount_minor"] == 839_160
    assert plans["watch"]["hostname_limit"] == 25

    for code in ("secure", "compliance"):
        assert plans[code]["purchasable"] is False
        assert plans[code]["monthly_amount_minor"] is None
        assert plans[code]["annual_amount_minor"] is None


# --- POST /billing/checkout ---


@pytest.mark.asyncio
async def test_checkout_for_a_non_purchasable_plan_returns_contact_us(
    owner_client: AsyncClient,
) -> None:
    response = await owner_client.post(
        "/api/v1/billing/checkout", json={"plan_code": "secure", "interval": "monthly"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"checkout_url": None, "provider": None, "contact_us": True}


@pytest.mark.asyncio
async def test_checkout_without_a_configured_provider_is_an_internal_error(
    db_session: AsyncSession,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        SESSION_SECRET="test-secret", CORS_ORIGINS="http://test"
    )
    app.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    try:
        client = await _new_client(None)
        try:
            await _login(client, fake_email_sender, _random_email())
            response = await client.post(
                "/api/v1/billing/checkout", json={"plan_code": "watch", "interval": "monthly"}
            )
            assert response.status_code == 500
            assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        finally:
            await client.aclose()
    finally:
        app.dependency_overrides.clear()


class FakeBillingProvider:
    provider = BillingProvider.STRIPE

    def __init__(self) -> None:
        self.checkout_calls: list[dict[str, object]] = []

    async def create_checkout_session(self, **kwargs: object) -> CheckoutSession:
        self.checkout_calls.append(kwargs)
        return CheckoutSession(
            checkout_url="https://checkout.stripe.com/test", provider_reference="cs_test_1"
        )

    def verify_and_parse_webhook(self, **_kwargs: object) -> None:  # pragma: no cover
        raise NotImplementedError

    async def cancel_subscription(self, provider_subscription_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_checkout_for_a_purchasable_plan_returns_the_providers_url(
    owner_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_provider = FakeBillingProvider()
    monkeypatch.setattr(
        "app.billing.service.get_billing_provider", lambda settings, currency: fake_provider
    )

    response = await owner_client.post(
        "/api/v1/billing/checkout", json={"plan_code": "watch", "interval": "annual"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["checkout_url"] == "https://checkout.stripe.com/test"
    assert body["provider"] == "stripe"
    assert body["contact_us"] is False

    assert len(fake_provider.checkout_calls) == 1
    call = fake_provider.checkout_calls[0]
    assert call["plan_code"] == "watch"
    assert call["amount_minor"] == 839_160

    # §7.11: checkout never writes a subscriptions row itself.
    subscription_response = await owner_client.get("/api/v1/billing/subscription")
    assert subscription_response.json() is None


# --- webhooks ---


def _stripe_signature(secret: str, raw_body: bytes, timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    signed_payload = f"{timestamp}.".encode() + raw_body
    v1 = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


def _razorpay_signature(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_stripe_webhook_rejects_an_invalid_signature(owner_client: AsyncClient) -> None:
    response = await owner_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=b'{"id": "evt_bad"}',
        headers={"stripe-signature": "t=1,v1=not-real"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEBHOOK_INVALID_SIGNATURE"


@pytest.mark.asyncio
async def test_razorpay_webhook_rejects_an_invalid_signature(owner_client: AsyncClient) -> None:
    response = await owner_client.post(
        "/api/v1/billing/webhooks/razorpay",
        content=b"{}",
        headers={"x-razorpay-signature": "not-real"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEBHOOK_INVALID_SIGNATURE"


@pytest.mark.asyncio
async def test_stripe_webhook_activates_subscription_and_is_idempotent_on_replay(
    owner_client: AsyncClient,
) -> None:
    org_response = await owner_client.get("/api/v1/orgs/current")
    org_id = org_response.json()["org_id"]

    payload = {
        "id": f"evt_activate_{uuid.uuid4().hex}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test123",
                "status": "active",
                "current_period_start": int(time.time()),
                "current_period_end": int(time.time()) + 2_592_000,
                "cancel_at_period_end": False,
                "metadata": {"org_id": org_id, "plan_code": "watch", "interval": "monthly"},
            }
        },
    }
    raw_body = json.dumps(payload).encode()
    signature = _stripe_signature(_WEBHOOK_SECRET, raw_body)

    first_response = await owner_client.post(
        "/api/v1/billing/webhooks/stripe", content=raw_body, headers={"stripe-signature": signature}
    )
    assert first_response.status_code == 200

    subscription_response = await owner_client.get("/api/v1/billing/subscription")
    body = subscription_response.json()
    assert body["state"] == "active"
    assert body["plan_code"] == "watch"
    assert body["provider_subscription_id"] == "sub_test123"

    org_after = await owner_client.get("/api/v1/orgs/current")
    assert org_after.json()["plan_code"] == "watch"

    # Replaying the exact same event id must not error and must not create
    # a second subscription row (§7.11 idempotency).
    second_response = await owner_client.post(
        "/api/v1/billing/webhooks/stripe", content=raw_body, headers={"stripe-signature": signature}
    )
    assert second_response.status_code == 200
    second_subscription = await owner_client.get("/api/v1/billing/subscription")
    assert second_subscription.json()["subscription_id"] == body["subscription_id"]


@pytest.mark.asyncio
async def test_razorpay_charged_webhook_creates_an_invoice(owner_client: AsyncClient) -> None:
    org_response = await owner_client.get("/api/v1/orgs/current")
    org_id = org_response.json()["org_id"]

    payload = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_rzp_1",
                    "notes": {"org_id": org_id, "gstin": "29ABCDE1234F2Z5"},
                }
            },
            "payment": {"entity": {"amount": 99900, "currency": "INR"}},
        },
    }
    raw_body = json.dumps(payload).encode()
    signature = _razorpay_signature(_WEBHOOK_SECRET, raw_body)

    response = await owner_client.post(
        "/api/v1/billing/webhooks/razorpay",
        content=raw_body,
        headers={"x-razorpay-signature": signature},
    )
    assert response.status_code == 200

    invoices_response = await owner_client.get("/api/v1/billing/invoices")
    invoices = invoices_response.json()
    assert invoices["total"] == 1
    invoice = invoices["items"][0]
    assert invoice["amount_minor"] == 99900
    assert invoice["currency"] == "INR"
    assert invoice["gstin"] == "29ABCDE1234F2Z5"
    assert invoice["number"].startswith(f"INV-{datetime.now(UTC).year}-")


# --- POST /billing/cancel ---


@pytest.mark.asyncio
async def test_cancel_with_no_subscription_is_not_found(owner_client: AsyncClient) -> None:
    response = await owner_client.post("/api/v1/billing/cancel")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cancel_sets_cancel_at_period_end_and_is_idempotent(
    owner_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id = uuid.UUID((await owner_client.get("/api/v1/orgs/current")).json()["org_id"])

    now = datetime.now(UTC)
    db_session.add(
        SubscriptionRecord(
            subscription_id=uuid.uuid4(),
            org_id=org_id,
            plan_code=PlanCode.WATCH.value,
            provider=BillingProvider.STRIPE.value,
            interval="monthly",
            currency="INR",
            state="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            cancel_at_period_end=False,
            provider_subscription_id="sub_cancel_me",
        )
    )
    await db_session.commit()

    cancel_calls: list[str] = []

    class _FakeCancelProvider:
        provider = BillingProvider.STRIPE

        async def cancel_subscription(self, provider_subscription_id: str) -> None:
            cancel_calls.append(provider_subscription_id)

    monkeypatch.setattr(
        "app.billing.service.get_billing_provider_by_name",
        lambda settings, provider: _FakeCancelProvider(),
    )

    first = await owner_client.post("/api/v1/billing/cancel")
    assert first.status_code == 200
    assert first.json()["cancel_at_period_end"] is True

    second = await owner_client.post("/api/v1/billing/cancel")
    assert second.status_code == 200
    assert second.json()["cancel_at_period_end"] is True

    # Idempotent: the provider is only actually asked to cancel once.
    assert cancel_calls == ["sub_cancel_me"]


# --- downgrade quota-block (§7.8, triggered from billing on cancellation) ---


@pytest.mark.asyncio
async def test_downgrade_blocks_excess_monitors_oldest_first_and_deletes_nothing(
    db_session: AsyncSession,
) -> None:
    org = OrganisationRecord(
        org_id=uuid.uuid4(), name="Downgrade Co", country="IN", currency="INR", plan_code="watch"
    )
    db_session.add(org)
    await db_session.flush()

    base_time = datetime.now(UTC)
    monitors = [
        MonitoredHostnameRecord(
            monitor_id=uuid.uuid4(),
            org_id=org.org_id,
            hostname=f"host{i}.example.com",
            port=443,
            state=MonitorState.ACTIVE.value,
            created_at=base_time + timedelta(seconds=i),
        )
        for i in range(5)
    ]
    for monitor in monitors:
        db_session.add(monitor)
    await db_session.commit()

    # free plan's hostname_limit is 3 (§5.1) — 2 of the 5 must be blocked.
    await apply_plan_downgrade(db_session, org, PlanCode.FREE)
    await db_session.commit()

    stmt = select(MonitoredHostnameRecord).where(MonitoredHostnameRecord.org_id == org.org_id)
    refreshed = {m.hostname: m.state for m in (await db_session.execute(stmt)).scalars().all()}

    assert len(refreshed) == 5  # nothing deleted
    blocked = {
        hostname
        for hostname, state in refreshed.items()
        if state == MonitorState.QUOTA_BLOCKED.value
    }
    active = {
        hostname for hostname, state in refreshed.items() if state == MonitorState.ACTIVE.value
    }
    assert blocked == {"host0.example.com", "host1.example.com"}  # oldest-first
    assert active == {"host2.example.com", "host3.example.com", "host4.example.com"}
