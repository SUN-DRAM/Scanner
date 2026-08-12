"""Gate C item 5: Sentry init is guarded entirely by SENTRY_DSN and must
never raise, whether or not a DSN is configured."""

from __future__ import annotations

from app.config import Settings
from app.observability import init_sentry


def test_init_sentry_is_a_noop_without_a_dsn() -> None:
    init_sentry(Settings())  # does not raise, does not import sentry_sdk's init path


def test_init_sentry_accepts_a_configured_dsn() -> None:
    settings = Settings(SENTRY_DSN="https://examplepublickey@o0.ingest.sentry.io/0")
    init_sentry(settings)  # does not raise
