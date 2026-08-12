"""LOG_LEVEL (contract §4) was a defined setting nothing ever applied —
`configure_logging` is what makes it real. See app/logging_config.py's
module docstring for why this matters for log hygiene, not just log volume:
without it, the app's own IP-free request log line never printed anything,
and even once it did, a bare format string silently dropped every
`extra={...}` field (request_id included) that a log call passed.
"""

from __future__ import annotations

import json
import logging

from app.config import Settings
from app.logging_config import _JsonFormatter, configure_logging


def test_configure_logging_applies_the_configured_level() -> None:
    configure_logging(Settings(LOG_LEVEL="warning"))
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_falls_back_to_info_for_an_unrecognised_level() -> None:
    configure_logging(Settings(LOG_LEVEL="not-a-real-level"))
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_is_case_insensitive() -> None:
    configure_logging(Settings(LOG_LEVEL="DEBUG"))
    assert logging.getLogger().level == logging.DEBUG


def _make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_includes_extra_fields() -> None:
    # This is the contract §7.4 promise ("request_id ... included in every
    # log line for that request") that a bare format string silently broke.
    formatted = _JsonFormatter().format(
        _make_record(request_id="req_abc123", status_code=200, duration_ms=42)
    )
    payload = json.loads(formatted)
    assert payload["message"] == "request"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req_abc123"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 42


def test_json_formatter_never_raises_on_an_unserializable_extra_value() -> None:
    formatted = _JsonFormatter().format(_make_record(weird=ValueError("boom")))
    payload = json.loads(formatted)  # does not raise
    assert "boom" in payload["weird"]
