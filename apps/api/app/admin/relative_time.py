"""Backend-authored relative-time strings for the admin dashboard
(contract §7.13). Rule 2: the frontend renders "3 days ago", it does not
compute it from a timestamp.
"""

from __future__ import annotations

from datetime import UTC, datetime

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY
_MONTH = 30 * _DAY
_YEAR = 365 * _DAY


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit} ago" if count == 1 else f"{count} {unit}s ago"


def format_relative(moment: datetime, now: datetime) -> str:
    """A coarse "N units ago" string. Clock skew (a moment slightly in the
    future) reads as "just now" rather than a negative count."""
    seconds = (now - _as_utc(moment)).total_seconds()
    if seconds < _MINUTE:
        return "just now"
    if seconds < _HOUR:
        return _plural(int(seconds // _MINUTE), "minute")
    if seconds < _DAY:
        return _plural(int(seconds // _HOUR), "hour")
    if seconds < _WEEK:
        return _plural(int(seconds // _DAY), "day")
    if seconds < _MONTH:
        return _plural(int(seconds // _WEEK), "week")
    if seconds < _YEAR:
        return _plural(int(seconds // _MONTH), "month")
    return _plural(int(seconds // _YEAR), "year")
