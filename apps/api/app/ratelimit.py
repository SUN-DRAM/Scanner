"""Redis sliding-window rate limiter (contract §10 rule 7)."""

from __future__ import annotations

import hashlib
import time

from redis.asyncio import Redis

WINDOW_SECONDS = 3600


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Rate limit exceeded, retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


def hash_for_bucket(value: str) -> str:
    """Key hash for the Redis sliding-window bucket only. This is distinct from
    the persisted `client_ip_hash` DB column (contract §11: `sha256(ip + salt)`)
    — no env var is defined for that salt yet (see CONTRACT GAP raised for
    Step 6). This hash only needs to consistently bucket the same client within
    a one-hour window that Redis expires on its own; it is never persisted."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _check_and_record(redis: Redis, key: str, limit: int, window_seconds: int) -> None:
    now = time.time()
    window_start = now - window_seconds

    await redis.zremrangebyscore(key, 0, window_start)
    count = await redis.zcard(key)

    if count >= limit:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        oldest_ts = oldest[0][1] if oldest else now
        retry_after = max(1, int(oldest_ts + window_seconds - now))
        raise RateLimitExceeded(retry_after)

    member = f"{now:.6f}:{count}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.zadd(key, {member: now})
        pipe.expire(key, window_seconds)
        await pipe.execute()


async def enforce_scan_rate_limits(
    redis: Redis,
    *,
    client_ip: str,
    hostname: str,
    per_ip_per_hour: int,
    per_hostname_per_hour: int,
    window_seconds: int = WINDOW_SECONDS,
) -> None:
    """Raises RateLimitExceeded (with the binding retry_after_seconds) if either
    the per-IP or per-hostname hourly limit is hit."""
    ip_key = f"ratelimit:ip:{hash_for_bucket(client_ip)}"
    hostname_key = f"ratelimit:hostname:{hash_for_bucket(hostname)}"
    await _check_and_record(redis, ip_key, per_ip_per_hour, window_seconds)
    await _check_and_record(redis, hostname_key, per_hostname_per_hour, window_seconds)


async def enforce_otp_request_rate_limits(
    redis: Redis,
    *,
    client_ip: str,
    email: str,
    per_email_per_hour: int = 3,
    per_ip_per_hour: int = 10,
    window_seconds: int = WINDOW_SECONDS,
) -> None:
    """Contract §7.6: 3 OTP requests per email per hour, 10 per IP per hour.
    Same sliding-window mechanism as `enforce_scan_rate_limits`, a distinct
    key prefix so the two buckets never collide."""
    email_key = f"ratelimit:otp:email:{hash_for_bucket(email)}"
    ip_key = f"ratelimit:otp:ip:{hash_for_bucket(client_ip)}"
    await _check_and_record(redis, email_key, per_email_per_hour, window_seconds)
    await _check_and_record(redis, ip_key, per_ip_per_hour, window_seconds)


async def enforce_monitor_scan_rate_limit(
    redis: Redis,
    *,
    monitor_id: str,
    limit_per_window: int = 1,
    window_seconds: int = 600,
) -> None:
    """Contract §7.8: one manual re-scan per monitor per 10 minutes. Same
    sliding-window mechanism as the other two limiters, its own key prefix
    and a 10-minute window rather than `WINDOW_SECONDS`'s hour."""
    key = f"ratelimit:monitor_scan:{hash_for_bucket(monitor_id)}"
    await _check_and_record(redis, key, limit_per_window, window_seconds)
