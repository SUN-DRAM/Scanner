"""Wires up `LOG_LEVEL` (contract §4), which was a defined `Settings` field
with nothing ever applying it — Python's logging defaults every logger to
WARNING, so `app/main.py`'s own per-request `logger.info("request", ...)`
line (method/path/status/duration, deliberately IP-free — see Gate C's log
hygiene item) never actually printed anything, in dev or prod. Confirmed
live: disabling uvicorn's own IP-containing access log
(`apps/api/Dockerfile.prod`) and expecting this line to take over request
visibility left zero request-level log output at all until this was wired
up. Called once, at process start, by both `app.main` (the API process) and
`app.worker` (the arq worker) — `logger.exception` calls in
`app/scanner/orchestrator.py` run in the worker process, not the API one,
and need this too.

Also fixes a second gap found alongside the first: a bare `%(message)s`
format string drops every `extra={...}` field a log call passes (they're
attached to the `LogRecord`, but a plain formatter never reads them) — so
even with the level fixed, `request_id` (contract §7.4: "included in every
log line for that request") silently wasn't. `_JsonFormatter` below
includes them, and is the more useful shape for a containerized app's
stdout anyway (structured, one log aggregator away from being queryable).
"""

from __future__ import annotations

import json
import logging

from app.config import Settings

_VALID_LEVELS = {"debug", "info", "warning", "error", "critical"}

# Attributes every LogRecord has regardless of what a call site passed via
# `extra=` — anything not in this set on a given record is exactly that
# call's extra data, e.g. request_id/method/path/status_code/duration_ms.
_STANDARD_LOG_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # default=str: never let one unserializable extra value (a stray
        # exception object, say) take down logging itself — the same
        # "degrade, don't crash" call as errors.py's _json_safe.
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    level_name = settings.log_level.lower()
    if level_name not in _VALID_LEVELS:
        level_name = "info"

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level_name.upper()))
    root.handlers = [handler]
