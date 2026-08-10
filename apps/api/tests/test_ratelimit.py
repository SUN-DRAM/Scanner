"""Tests for the Redis sliding-window rate limiter (contract §10 rule 7)."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from app.ratelimit import RateLimitExceeded, enforce_scan_rate_limits, hash_for_bucket


@pytest.mark.asyncio
async def test_rate_limiter_trips_at_the_configured_threshold(redis_client: Redis) -> None:
    limit = 3
    client_ip = f"203.0.113.{uuid.uuid4().int % 250}"
    hostname = f"test-{uuid.uuid4().hex}.example.com"

    try:
        for _ in range(limit):
            await enforce_scan_rate_limits(
                redis_client,
                client_ip=client_ip,
                hostname=hostname,
                per_ip_per_hour=limit,
                per_hostname_per_hour=100,
            )

        with pytest.raises(RateLimitExceeded) as exc_info:
            await enforce_scan_rate_limits(
                redis_client,
                client_ip=client_ip,
                hostname=hostname,
                per_ip_per_hour=limit,
                per_hostname_per_hour=100,
            )
        assert exc_info.value.retry_after_seconds > 0
    finally:
        await redis_client.delete(f"ratelimit:ip:{hash_for_bucket(client_ip)}")
        await redis_client.delete(f"ratelimit:hostname:{hash_for_bucket(hostname)}")


@pytest.mark.asyncio
async def test_rate_limiter_trips_on_hostname_limit_independently_of_ip(
    redis_client: Redis,
) -> None:
    limit = 2
    client_ip = f"203.0.113.{uuid.uuid4().int % 250}"
    hostname = f"test-{uuid.uuid4().hex}.example.com"

    try:
        for _ in range(limit):
            await enforce_scan_rate_limits(
                redis_client,
                client_ip=client_ip,
                hostname=hostname,
                per_ip_per_hour=100,
                per_hostname_per_hour=limit,
            )

        with pytest.raises(RateLimitExceeded):
            await enforce_scan_rate_limits(
                redis_client,
                client_ip=client_ip,
                hostname=hostname,
                per_ip_per_hour=100,
                per_hostname_per_hour=limit,
            )
    finally:
        await redis_client.delete(f"ratelimit:ip:{hash_for_bucket(client_ip)}")
        await redis_client.delete(f"ratelimit:hostname:{hash_for_bucket(hostname)}")


@pytest.mark.asyncio
async def test_rate_limiter_allows_requests_under_the_threshold(redis_client: Redis) -> None:
    client_ip = f"203.0.113.{uuid.uuid4().int % 250}"
    hostname = f"test-{uuid.uuid4().hex}.example.com"

    try:
        await enforce_scan_rate_limits(
            redis_client,
            client_ip=client_ip,
            hostname=hostname,
            per_ip_per_hour=5,
            per_hostname_per_hour=5,
        )
    finally:
        await redis_client.delete(f"ratelimit:ip:{hash_for_bucket(client_ip)}")
        await redis_client.delete(f"ratelimit:hostname:{hash_for_bucket(hostname)}")
