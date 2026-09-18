"""Outreach orchestrator (contract §7.15/§11, v3.6, docs/OUTREACH_BUILD_SPEC.md).

Internal GTM tooling, admin-only, never customer-facing (see `ROADMAP.md`'s
"Internal tooling" section). Contains no security logic of its own — it
calls the scan engine directly and reads its stored results; findings are
referenced, never copied.
"""
