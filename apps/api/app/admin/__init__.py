"""Internal admin dashboard (contract §7.13, amendment v2.8).

Read-mostly, single-operator console for cold outreach and operations,
gated by `ADMIN_TOKEN` (§4). Nothing here mutates customer data — the only
writes anywhere on this surface are prospect-scan batches, which touch no
customer-owned table.
"""
