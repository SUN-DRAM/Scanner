"""Sentry error tracking (Gate C item 5), guarded entirely by `SENTRY_DSN`.

Shared between the API process (`app.main`) and the arq worker
(`app.worker`) — both need it, since scan orchestration failures are caught
and logged (`logger.exception`, `app/scanner/orchestrator.py`) inside the
worker process, not the API process. Sentry's `LoggingIntegration` turns
those `logger.exception` calls into events automatically once initialised —
no extra instrumentation needed at the call site.

DPDP posture (CLAUDE.md rule 10): `send_default_pii=False` — Sentry never
receives raw client IPs or request bodies, matching the app's own "hash the
IP, never store it raw" rule. Nothing here overrides that.
"""

from __future__ import annotations

from app.config import Settings


def init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        # Light default: enough to see slow endpoints without paying to
        # trace every health-check poll. Tune from the Sentry project
        # settings, not by raising this blind.
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
