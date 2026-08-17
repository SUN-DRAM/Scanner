"""Razorpay and Stripe clients (contract §7.11): starting a checkout,
verifying + parsing a webhook delivery, and cancelling at period end. Both
providers sit behind one `BillingProviderClient` protocol so
`app/billing/service.py` never branches on provider name outside this
module — the same shape `app/notify/email.py`'s `EmailSender` gives Step 2's
OTP delivery.

Neither provider's official SDK is a dependency here, matching
`ResendEmailSender`'s own "just the one call this product needs" choice —
`httpx` plus each provider's plain HTTP API is enough for a checkout
session, a cancel call, and HMAC signature verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings
from app.enums import BillingInterval, BillingProvider, Currency

logger = logging.getLogger("app.billing.providers")

_STRIPE_WEBHOOK_TOLERANCE_SECONDS = 300  # 5 minutes, standard Stripe guidance


class BillingNotConfiguredError(Exception):
    """Raised when the env vars for a currency's provider (§4) are empty."""


class ProviderRequestError(Exception):
    """A provider's API returned a non-2xx or the request itself failed."""


class SignatureVerificationError(Exception):
    """A webhook's signature didn't verify against the configured secret."""


@dataclass(frozen=True)
class CheckoutSession:
    checkout_url: str
    provider_reference: str


@dataclass(frozen=True)
class WebhookEvent:
    """The one shape both providers' wildly different payloads are parsed
    into (CONTRACT.md §14 v2.5), so `app/billing/service.py` has a single
    code path applying state regardless of which provider sent it.
    `event_type` is one of: "subscription.checkout_completed" (Stripe only —
    org linkage without period data yet), "subscription.active",
    "subscription.past_due", "subscription.cancelled",
    "subscription.charged", or "subscription.other" (ignored, logged only).
    Unix-second timestamps, matching both providers' own wire format."""

    event_id: str
    event_type: str
    raw_type: str
    org_id: str | None
    provider_subscription_id: str | None
    plan_code: str | None
    interval: str | None
    current_period_start: int | None
    current_period_end: int | None
    cancel_at_period_end: bool | None
    charge_amount_minor: int | None
    charge_currency: str | None
    gstin: str | None
    place_of_supply: str | None


class BillingProviderClient(Protocol):
    provider: BillingProvider

    async def create_checkout_session(
        self,
        *,
        org_id: str,
        plan_code: str,
        interval: BillingInterval,
        amount_minor: int,
        currency: Currency,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        gstin: str | None,
        place_of_supply: str | None,
    ) -> CheckoutSession: ...

    def verify_and_parse_webhook(
        self, *, raw_body: bytes, headers: dict[str, str]
    ) -> WebhookEvent: ...

    async def cancel_subscription(self, provider_subscription_id: str) -> None: ...


def _notes(
    *,
    org_id: str,
    plan_code: str,
    interval: BillingInterval,
    gstin: str | None,
    place_of_supply: str | None,
) -> dict[str, str]:
    """Shared metadata/notes payload both providers attach to the checkout
    they create — the only place `org_id`/`plan_code`/`interval`/the GST
    fields survive between "checkout started" and "a webhook confirms it"
    (§7.11: no `subscriptions` row exists yet to hold them)."""
    notes = {"org_id": org_id, "plan_code": plan_code, "interval": interval.value}
    if gstin:
        notes["gstin"] = gstin
    if place_of_supply:
        notes["place_of_supply"] = place_of_supply
    return notes


class RazorpayClient:
    provider = BillingProvider.RAZORPAY
    _BASE_URL = "https://api.razorpay.com/v1"
    # ~10 years of billing cycles before Razorpay's own `total_count` ceiling
    # is reached (a subscription that outlives this needs a fresh checkout —
    # not expected to matter inside Phase 2's test-mode lifetime).
    _TOTAL_COUNT = {BillingInterval.MONTHLY: 120, BillingInterval.ANNUAL: 10}

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret

    async def create_checkout_session(
        self,
        *,
        org_id: str,
        plan_code: str,
        interval: BillingInterval,
        amount_minor: int,
        currency: Currency,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        gstin: str | None,
        place_of_supply: str | None,
    ) -> CheckoutSession:
        notes = _notes(
            org_id=org_id,
            plan_code=plan_code,
            interval=interval,
            gstin=gstin,
            place_of_supply=place_of_supply,
        )
        period = "monthly" if interval == BillingInterval.MONTHLY else "yearly"

        async with httpx.AsyncClient(
            timeout=15.0, auth=(self._key_id, self._key_secret)
        ) as client:
            plan_response = await client.post(
                f"{self._BASE_URL}/plans",
                json={
                    "period": period,
                    "interval": 1,
                    "item": {
                        "name": f"SUN-DRAM Scanner — {plan_code} ({interval.value})",
                        "amount": amount_minor,
                        "currency": currency.value,
                    },
                    "notes": notes,
                },
            )
            if plan_response.status_code >= 400:
                raise ProviderRequestError(
                    f"Razorpay plan creation failed: {plan_response.status_code}"
                )
            plan_id = plan_response.json()["id"]

            subscription_response = await client.post(
                f"{self._BASE_URL}/subscriptions",
                json={
                    "plan_id": plan_id,
                    "total_count": self._TOTAL_COUNT[interval],
                    "customer_notify": 1,
                    "notes": notes,
                },
            )
        if subscription_response.status_code >= 400:
            raise ProviderRequestError(
                f"Razorpay subscription creation failed: {subscription_response.status_code}"
            )
        body = subscription_response.json()
        return CheckoutSession(checkout_url=body["short_url"], provider_reference=body["id"])

    def verify_and_parse_webhook(
        self, *, raw_body: bytes, headers: dict[str, str]
    ) -> WebhookEvent:
        signature = headers.get("x-razorpay-signature", "")
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise SignatureVerificationError("Invalid Razorpay webhook signature.")

        payload = json.loads(raw_body)
        raw_type = str(payload.get("event", ""))

        entity: dict[str, object] = {}
        notes: dict[str, str] = {}
        period_start: int | None = None
        period_end: int | None = None
        provider_subscription_id: str | None = None
        cancel_at_period_end: bool | None = None
        charge_amount: int | None = None
        charge_currency: str | None = None

        if raw_type.startswith("subscription."):
            entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
            raw_notes = entity.get("notes")
            if isinstance(raw_notes, dict):
                notes = {str(k): str(v) for k, v in raw_notes.items()}
            provider_subscription_id = entity.get("id")  # type: ignore[assignment]
            period_start = entity.get("current_start")  # type: ignore[assignment]
            period_end = entity.get("current_end")  # type: ignore[assignment]
            if raw_type == "subscription.cancelled":
                cancel_at_period_end = False  # already happened — nothing left to defer
        if raw_type == "subscription.charged":
            payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            charge_amount = payment_entity.get("amount")
            charge_currency = payment_entity.get("currency")

        event_type = {
            "subscription.activated": "subscription.active",
            "subscription.charged": "subscription.charged",
            "subscription.cancelled": "subscription.cancelled",
            "subscription.completed": "subscription.cancelled",
            "subscription.halted": "subscription.past_due",
        }.get(raw_type, "subscription.other")

        # Razorpay's own webhook payload has no top-level delivery id in
        # every account/version — a stable hash of the raw body is an
        # equally valid dedup key (identical retries produce an identical
        # hash) and never blocks on a field that may not be there.
        event_id = str(payload.get("id") or hashlib.sha256(raw_body).hexdigest())

        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            raw_type=raw_type,
            org_id=notes.get("org_id"),
            provider_subscription_id=provider_subscription_id,
            plan_code=notes.get("plan_code"),
            interval=notes.get("interval"),
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
            charge_amount_minor=charge_amount,
            charge_currency=charge_currency,
            gstin=notes.get("gstin"),
            place_of_supply=notes.get("place_of_supply"),
        )

    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        async with httpx.AsyncClient(
            timeout=15.0, auth=(self._key_id, self._key_secret)
        ) as client:
            response = await client.post(
                f"{self._BASE_URL}/subscriptions/{provider_subscription_id}/cancel",
                json={"cancel_at_cycle_end": 1},
            )
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"Razorpay subscription cancel failed: {response.status_code}"
            )


class StripeClient:
    provider = BillingProvider.STRIPE
    _BASE_URL = "https://api.stripe.com/v1"

    def __init__(self, secret_key: str, webhook_secret: str) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret

    async def create_checkout_session(
        self,
        *,
        org_id: str,
        plan_code: str,
        interval: BillingInterval,
        amount_minor: int,
        currency: Currency,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        gstin: str | None,
        place_of_supply: str | None,
    ) -> CheckoutSession:
        stripe_interval = "month" if interval == BillingInterval.MONTHLY else "year"
        product_name = f"SUN-DRAM Scanner — {plan_code} ({interval.value})"

        form: dict[str, str] = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "customer_email": customer_email,
            "client_reference_id": org_id,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.value.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_minor),
            "line_items[0][price_data][recurring][interval]": stripe_interval,
            "line_items[0][price_data][product_data][name]": product_name,
            "metadata[org_id]": org_id,
            "metadata[plan_code]": plan_code,
            "metadata[interval]": interval.value,
            "subscription_data[metadata][org_id]": org_id,
            "subscription_data[metadata][plan_code]": plan_code,
            "subscription_data[metadata][interval]": interval.value,
        }
        if gstin:
            form["metadata[gstin]"] = gstin
            form["subscription_data[metadata][gstin]"] = gstin
        if place_of_supply:
            form["metadata[place_of_supply]"] = place_of_supply
            form["subscription_data[metadata][place_of_supply]"] = place_of_supply

        # Stripe's API is form-encoded, not JSON, and expects nested fields
        # as PHP-style bracket keys (`line_items[0][price_data][currency]`)
        # — `form` above is already built pre-flattened as those keys, so a
        # plain form POST (no recursive flattener needed for this one shape)
        # sends it correctly.
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._BASE_URL}/checkout/sessions",
                data=form,
                headers={"Authorization": f"Bearer {self._secret_key}"},
            )
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"Stripe checkout session creation failed: {response.status_code}"
            )
        body = response.json()
        return CheckoutSession(checkout_url=body["url"], provider_reference=body["id"])

    def _verify_signature(self, raw_body: bytes, signature_header: str) -> None:
        if not signature_header:
            raise SignatureVerificationError("Missing Stripe-Signature header.")
        parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
        timestamp = parts.get("t")
        v1 = parts.get("v1")
        if not timestamp or not v1:
            raise SignatureVerificationError("Malformed Stripe-Signature header.")

        signed_payload = f"{timestamp}.".encode() + raw_body
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, v1):
            raise SignatureVerificationError("Invalid Stripe webhook signature.")
        if abs(time.time() - int(timestamp)) > _STRIPE_WEBHOOK_TOLERANCE_SECONDS:
            raise SignatureVerificationError("Stripe webhook timestamp outside tolerance.")

    def verify_and_parse_webhook(
        self, *, raw_body: bytes, headers: dict[str, str]
    ) -> WebhookEvent:
        self._verify_signature(raw_body, headers.get("stripe-signature", ""))

        payload = json.loads(raw_body)
        raw_type = str(payload.get("type", ""))
        event_id = str(payload.get("id", ""))
        data_object = payload.get("data", {}).get("object", {})
        metadata = {str(k): str(v) for k, v in (data_object.get("metadata") or {}).items()}

        event_type = "subscription.other"
        org_id: str | None = metadata.get("org_id")
        provider_subscription_id: str | None = None
        period_start: int | None = None
        period_end: int | None = None
        cancel_at_period_end: bool | None = None
        charge_amount: int | None = None
        charge_currency: str | None = None

        if raw_type == "checkout.session.completed":
            event_type = "subscription.checkout_completed"
            org_id = data_object.get("client_reference_id") or org_id
            provider_subscription_id = data_object.get("subscription")
        elif raw_type in ("customer.subscription.created", "customer.subscription.updated"):
            provider_subscription_id = data_object.get("id")
            status = data_object.get("status")
            period_start = data_object.get("current_period_start")
            period_end = data_object.get("current_period_end")
            cancel_at_period_end = data_object.get("cancel_at_period_end")
            event_type = (
                "subscription.active"
                if status == "active"
                else "subscription.past_due"
                if status == "past_due"
                else "subscription.other"
            )
        elif raw_type == "customer.subscription.deleted":
            event_type = "subscription.cancelled"
            provider_subscription_id = data_object.get("id")
        elif raw_type == "invoice.paid":
            event_type = "subscription.charged"
            provider_subscription_id = data_object.get("subscription")
            charge_amount = data_object.get("amount_paid")
            currency_value = data_object.get("currency")
            charge_currency = currency_value.upper() if currency_value else None

        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            raw_type=raw_type,
            org_id=org_id,
            provider_subscription_id=provider_subscription_id,
            plan_code=metadata.get("plan_code"),
            interval=metadata.get("interval"),
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
            charge_amount_minor=charge_amount,
            charge_currency=charge_currency,
            gstin=metadata.get("gstin"),
            place_of_supply=metadata.get("place_of_supply"),
        )

    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._BASE_URL}/subscriptions/{provider_subscription_id}",
                data={"cancel_at_period_end": "true"},
                headers={"Authorization": f"Bearer {self._secret_key}"},
            )
        if response.status_code >= 400:
            raise ProviderRequestError(f"Stripe subscription cancel failed: {response.status_code}")


def get_billing_provider_by_name(
    settings: Settings, provider: BillingProvider
) -> BillingProviderClient:
    if provider == BillingProvider.RAZORPAY:
        if not (
            settings.razorpay_key_id
            and settings.razorpay_key_secret
            and settings.razorpay_webhook_secret
        ):
            raise BillingNotConfiguredError("Razorpay is not configured yet.")
        return RazorpayClient(
            settings.razorpay_key_id, settings.razorpay_key_secret, settings.razorpay_webhook_secret
        )
    if not (settings.stripe_secret_key and settings.stripe_webhook_secret):
        raise BillingNotConfiguredError("Stripe is not configured yet.")
    return StripeClient(settings.stripe_secret_key, settings.stripe_webhook_secret)


def get_billing_provider(settings: Settings, currency: Currency) -> BillingProviderClient:
    """§7.11: "Provider is selected from Organisation.currency (INR ->
    razorpay, else stripe) — never a request field."""
    provider = BillingProvider.RAZORPAY if currency == Currency.INR else BillingProvider.STRIPE
    return get_billing_provider_by_name(settings, provider)
