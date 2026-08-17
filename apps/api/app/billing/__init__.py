"""Billing (contract §7.11, Phase 2 Step 6): pricing, checkout, webhooks,
cancellation, invoices. `providers.py` talks to Razorpay/Stripe; `service.py`
is the provider-agnostic business logic `routers/billing.py` calls into.
"""

from __future__ import annotations
