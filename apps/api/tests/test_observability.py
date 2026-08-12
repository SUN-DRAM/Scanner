"""Gate C item 5: Sentry init is guarded entirely by SENTRY_DSN and must
never raise, whether or not a DSN is configured.

`sentry_sdk.init()` is mocked rather than actually called with a
DSN-shaped string: the real thing installs process-global logging hooks
(LoggingIntegration) that outlive the test — confirmed live, a first
version of this file that called the real `init_sentry` with a
well-formed-but-fake DSN left every subsequent test in the same `pytest`
process attempting real network calls to Sentry's ingestion endpoint from
inside ordinary `logger.info(...)` calls, failing loudly (though not
test-failingly) with "Logging error" tracebacks for the rest of the run.
"""

from __future__ import annotations

from unittest.mock import patch

from app.config import Settings
from app.observability import init_sentry


def test_init_sentry_is_a_noop_without_a_dsn() -> None:
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(Settings())
    mock_init.assert_not_called()


def test_init_sentry_calls_sentry_sdk_init_with_the_configured_dsn() -> None:
    settings = Settings(
        SENTRY_DSN="https://examplepublickey@o0.ingest.sentry.io/0", APP_ENV="production"
    )
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(settings)
    mock_init.assert_called_once()
    _args, kwargs = mock_init.call_args
    assert kwargs["dsn"] == settings.sentry_dsn
    assert kwargs["environment"] == "production"
    # DPDP posture (CLAUDE.md rule 10): never send raw client IPs/request
    # bodies to a third party either.
    assert kwargs["send_default_pii"] is False
