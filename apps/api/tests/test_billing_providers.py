"""Unit tests for app/billing/providers.py: signature verification and
webhook parsing for both providers, offline — no network call, no DB, no
Redis (verify_and_parse_webhook is pure; only create_checkout_session/
cancel_subscription touch the network, and those aren't exercised here).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.billing.providers import (
    RazorpayClient,
    SignatureVerificationError,
    StripeClient,
    get_billing_provider,
    get_billing_provider_by_name,
)
from app.config import Settings
from app.enums import BillingProvider, Currency


def _razorpay_signature(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def _stripe_signature(secret: str, raw_body: bytes, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + raw_body
    v1 = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


# --- Razorpay ---


def test_razorpay_rejects_a_bad_signature() -> None:
    client = RazorpayClient("id", "secret", "webhook_secret")
    raw_body = b'{"event": "subscription.activated"}'
    with pytest.raises(SignatureVerificationError):
        client.verify_and_parse_webhook(
            raw_body=raw_body, headers={"x-razorpay-signature": "not-the-real-signature"}
        )


def test_razorpay_rejects_a_missing_signature() -> None:
    client = RazorpayClient("id", "secret", "webhook_secret")
    with pytest.raises(SignatureVerificationError):
        client.verify_and_parse_webhook(raw_body=b"{}", headers={})


def test_razorpay_parses_subscription_activated() -> None:
    client = RazorpayClient("id", "secret", "webhook_secret")
    payload = {
        "event": "subscription.activated",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_test123",
                    "current_start": 1_700_000_000,
                    "current_end": 1_702_592_000,
                    "notes": {"org_id": "org-1", "plan_code": "watch", "interval": "monthly"},
                }
            }
        },
    }
    raw_body = json.dumps(payload).encode()
    signature = _razorpay_signature("webhook_secret", raw_body)

    event = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"x-razorpay-signature": signature}
    )

    assert event.event_type == "subscription.active"
    assert event.org_id == "org-1"
    assert event.plan_code == "watch"
    assert event.interval == "monthly"
    assert event.provider_subscription_id == "sub_test123"
    assert event.current_period_start == 1_700_000_000
    assert event.current_period_end == 1_702_592_000


def test_razorpay_parses_subscription_charged_with_payment_amount() -> None:
    client = RazorpayClient("id", "secret", "webhook_secret")
    payload = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_test123",
                    "notes": {"org_id": "org-1", "gstin": "29ABCDE1234F2Z5"},
                }
            },
            "payment": {"entity": {"amount": 99900, "currency": "INR"}},
        },
    }
    raw_body = json.dumps(payload).encode()
    signature = _razorpay_signature("webhook_secret", raw_body)

    event = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"x-razorpay-signature": signature}
    )

    assert event.event_type == "subscription.charged"
    assert event.charge_amount_minor == 99900
    assert event.charge_currency == "INR"
    assert event.gstin == "29ABCDE1234F2Z5"


def test_razorpay_replayed_delivery_produces_the_same_event_id() -> None:
    """No top-level id in this payload shape — event_id falls back to a
    content hash, which must be stable across identical retried deliveries
    for §7.11's idempotency guard to actually catch them."""
    client = RazorpayClient("id", "secret", "webhook_secret")
    payload = {"event": "subscription.cancelled", "payload": {"subscription": {"entity": {}}}}
    raw_body = json.dumps(payload).encode()
    signature = _razorpay_signature("webhook_secret", raw_body)

    first = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"x-razorpay-signature": signature}
    )
    second = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"x-razorpay-signature": signature}
    )
    assert first.event_id == second.event_id
    assert first.event_type == "subscription.cancelled"


# --- Stripe ---


def test_stripe_rejects_a_bad_signature() -> None:
    client = StripeClient("sk_test", "webhook_secret")
    with pytest.raises(SignatureVerificationError):
        client.verify_and_parse_webhook(
            raw_body=b"{}", headers={"stripe-signature": "t=1,v1=deadbeef"}
        )


def test_stripe_rejects_a_missing_signature() -> None:
    client = StripeClient("sk_test", "webhook_secret")
    with pytest.raises(SignatureVerificationError):
        client.verify_and_parse_webhook(raw_body=b"{}", headers={})


def test_stripe_rejects_a_stale_timestamp() -> None:
    client = StripeClient("sk_test", "webhook_secret")
    raw_body = b'{"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {}}}'
    stale_timestamp = int(time.time()) - 3600
    signature = _stripe_signature("webhook_secret", raw_body, stale_timestamp)
    with pytest.raises(SignatureVerificationError):
        client.verify_and_parse_webhook(
            raw_body=raw_body, headers={"stripe-signature": signature}
        )


def test_stripe_parses_checkout_session_completed() -> None:
    client = StripeClient("sk_test", "webhook_secret")
    payload = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "org-1",
                "subscription": "sub_test123",
                "metadata": {"org_id": "org-1", "plan_code": "watch", "interval": "monthly"},
            }
        },
    }
    raw_body = json.dumps(payload).encode()
    timestamp = int(time.time())
    signature = _stripe_signature("webhook_secret", raw_body, timestamp)

    event = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"stripe-signature": signature}
    )

    assert event.event_id == "evt_1"
    assert event.event_type == "subscription.checkout_completed"
    assert event.org_id == "org-1"
    assert event.provider_subscription_id == "sub_test123"


def test_stripe_parses_subscription_updated_to_active() -> None:
    client = StripeClient("sk_test", "webhook_secret")
    payload = {
        "id": "evt_2",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test123",
                "status": "active",
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_702_592_000,
                "cancel_at_period_end": False,
                "metadata": {"org_id": "org-1", "plan_code": "watch", "interval": "monthly"},
            }
        },
    }
    raw_body = json.dumps(payload).encode()
    timestamp = int(time.time())
    signature = _stripe_signature("webhook_secret", raw_body, timestamp)

    event = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"stripe-signature": signature}
    )

    assert event.event_type == "subscription.active"
    assert event.current_period_start == 1_700_000_000
    assert event.current_period_end == 1_702_592_000
    assert event.cancel_at_period_end is False


def test_stripe_parses_invoice_paid() -> None:
    client = StripeClient("sk_test", "webhook_secret")
    payload = {
        "id": "evt_3",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_test123",
                "amount_paid": 2900,
                "currency": "usd",
                "metadata": {"org_id": "org-1"},
            }
        },
    }
    raw_body = json.dumps(payload).encode()
    timestamp = int(time.time())
    signature = _stripe_signature("webhook_secret", raw_body, timestamp)

    event = client.verify_and_parse_webhook(
        raw_body=raw_body, headers={"stripe-signature": signature}
    )

    assert event.event_type == "subscription.charged"
    assert event.charge_amount_minor == 2900
    assert event.charge_currency == "USD"


# --- provider selection ---


def test_currency_selects_provider() -> None:
    settings = Settings(
        RAZORPAY_KEY_ID="id",
        RAZORPAY_KEY_SECRET="secret",
        RAZORPAY_WEBHOOK_SECRET="whsecret",
        STRIPE_SECRET_KEY="sk_test",
        STRIPE_WEBHOOK_SECRET="whsecret",
    )
    assert get_billing_provider(settings, Currency.INR).provider == BillingProvider.RAZORPAY
    assert get_billing_provider(settings, Currency.USD).provider == BillingProvider.STRIPE


def test_unconfigured_provider_raises() -> None:
    from app.billing.providers import BillingNotConfiguredError

    settings = Settings()
    with pytest.raises(BillingNotConfiguredError):
        get_billing_provider_by_name(settings, BillingProvider.RAZORPAY)
    with pytest.raises(BillingNotConfiguredError):
        get_billing_provider_by_name(settings, BillingProvider.STRIPE)
