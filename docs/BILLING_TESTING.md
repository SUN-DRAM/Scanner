# Billing testing (Phase 2 Step 6)

Test mode throughout — never live keys, per `docs/PHASE_2_PROMPT.md` Step 6 and CLAUDE.md rule "you will never see a live API key." This document is how a human exercises `POST /api/v1/billing/checkout` and the two webhook endpoints end to end against real Razorpay/Stripe test environments; it doesn't replace `pytest`, which covers signature verification, idempotency, and RBAC offline.

## Prerequisites

- A Razorpay account with **Test Mode** enabled (toggle, top-right of the dashboard) and a Stripe account (test keys are the default `sk_test_...` ones — no toggle needed).
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `STRIPE_SECRET_KEY` set in `.env` (see `.env.example`) from each dashboard's API Keys page.
- `RAZORPAY_WEBHOOK_SECRET` / `STRIPE_WEBHOOK_SECRET` — see "Webhook secrets" below; both are blank until you've created a webhook (dashboard) or started a forwarding session (Stripe CLI).
- `docker compose up --build` running locally, or the equivalent on `sundram.tech` (§7.11: webhooks must be reachable from the public internet — register the endpoint URLs there as `https://sundram.tech/api/v1/billing/webhooks/{razorpay,stripe}`, the domain, never the IP).

## Test cards

**Razorpay** (any test-mode checkout, via the `short_url` `POST /billing/checkout` returns):
| Card | Number | Result |
|---|---|---|
| Success | `4111 1111 1111 1111` | Payment succeeds — any future expiry, any CVV, any name |
| Failure | `4000 0000 0000 0002` | Payment declined |

UPI (Razorpay test mode): use `success@razorpay` as the VPA to simulate a successful UPI collect request.

**Stripe** (at the Checkout Session URL `POST /billing/checkout` returns):
| Card | Number | Result |
|---|---|---|
| Success | `4242 4242 4242 4242` | Payment succeeds — any future expiry, any CVV, any postal code |
| Requires authentication (3DS) | `4000 0027 6000 3184` | Exercises the 3DS challenge screen |
| Decline | `4000 0000 0000 0002` | Payment declined |

## Exercising checkout

```
POST /api/v1/billing/checkout
{ "plan_code": "watch", "interval": "monthly" }
```
as an org owner (see `apps/api/tests/test_billing_router.py` for the login flow, or use `/login` on the running web app once Step 7 ships it). The response's `checkout_url` is a real Razorpay/Stripe hosted page — open it, pay with a test card above, and watch the api/worker logs for `billing_webhook_duplicate`/`billing_webhook_ignored`/an applied event as the provider's webhook lands.

## Webhook secrets and replay

**Razorpay** — dashboard → Settings → Webhooks → Add New Webhook:
- URL: `https://sundram.tech/api/v1/billing/webhooks/razorpay` (production) or an `ngrok`/similar tunnel to `localhost:8000` for local testing — Razorpay's dashboard webhook sender needs a public URL, there is no CLI replay tool.
- Active events: `subscription.activated`, `subscription.charged`, `subscription.cancelled`, `subscription.completed`, `subscription.halted`.
- Copy the **Secret** shown into `RAZORPAY_WEBHOOK_SECRET`.
- Replay a delivery: dashboard → Webhooks → (the webhook) → Logs → pick a delivery → **Resend** — this is also the idempotency test: `docker compose logs api | grep billing_webhook_duplicate` should show it was recognised and skipped, not re-applied.

**Stripe** — the Stripe CLI is the fast local path, no tunnel needed:
```bash
stripe login
stripe listen --forward-to localhost:8000/api/v1/billing/webhooks/stripe
```
`stripe listen` prints a `whsec_...` value — put that in `STRIPE_WEBHOOK_SECRET` (it's session-specific; re-running `stripe listen` prints a new one). Trigger events directly, no real checkout needed:
```bash
stripe trigger checkout.session.completed
stripe trigger customer.subscription.updated
stripe trigger invoice.paid
stripe trigger customer.subscription.deleted
```
Replay the exact same delivery to test idempotency:
```bash
stripe events resend evt_...   # event id printed by `stripe listen` or `stripe trigger`
```
For production, add the endpoint in the dashboard (Developers → Webhooks → Add endpoint) at `https://sundram.tech/api/v1/billing/webhooks/stripe`, select the four event types above, and copy its **Signing secret** into `STRIPE_WEBHOOK_SECRET` — a CLI-forwarding secret and a dashboard-endpoint secret are different values; don't reuse one for the other.

## What a passing run looks like

1. `POST /billing/checkout` returns a real `checkout_url`; `GET /billing/subscription` is still `null` (§7.11: the redirect alone never writes a subscription).
2. Completing checkout (or `stripe trigger checkout.session.completed` + `customer.subscription.updated`) lands a webhook; `GET /billing/subscription` now returns `state: "active"` and `Organisation.plan_code` matches the purchased plan.
3. A charge event (`subscription.charged` / `invoice.paid`) appears in `GET /billing/invoices`.
4. `POST /billing/cancel` sets `cancel_at_period_end: true` immediately; plan access and quota are unchanged until `current_period_end`.
5. Resending the same webhook delivery a second time changes nothing (`billing_webhook_duplicate` in the logs) — confirms the acceptance-list item "both webhook endpoints... are idempotent on replay."
6. A payload with a corrupted signature (edit one character of `stripe-signature`/`x-razorpay-signature` with `curl`) gets `400 WEBHOOK_INVALID_SIGNATURE`.
