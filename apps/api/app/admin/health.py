"""Account-health classification (contract §7.13).

`AccountHealth` (§5) is derived server-side from these named constants with
a fixed precedence, since the outreach prompt's rules overlap and the
Health column holds one value:

1. dormant   — no login on record, or last login 30+ days ago
2. at_risk   — has >=1 hostname and last login 14+ days ago
3. stalled   — zero hostnames added
4. activated — has >=1 hostname and a login on record

`paying` is not a health value: a paid account is the separate `is_paying`
boolean on `AdminAccountRow`, so a paying customer who has gone quiet still
reads as at_risk/dormant here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.enums import AccountHealth

AT_RISK_LOGIN_SILENCE_DAYS = 14
DORMANT_LOGIN_SILENCE_DAYS = 30


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def compute_account_health(
    *,
    hostname_count: int,
    last_login_at: datetime | None,
    now: datetime,
) -> AccountHealth:
    if last_login_at is None:
        return AccountHealth.DORMANT

    silence_days = (now - _as_utc(last_login_at)).days
    if silence_days >= DORMANT_LOGIN_SILENCE_DAYS:
        return AccountHealth.DORMANT
    if hostname_count == 0:
        return AccountHealth.STALLED
    if silence_days >= AT_RISK_LOGIN_SILENCE_DAYS:
        return AccountHealth.AT_RISK
    return AccountHealth.ACTIVATED
