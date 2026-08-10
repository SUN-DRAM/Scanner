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
