"""Shared pytest fixtures."""

from __future__ import annotations

import socket
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.config import get_settings


def _has_internet() -> bool:
    try:
        socket.setdefaulttimeout(3)
        socket.gethostbyname("google.com")
        return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def require_internet() -> None:
    """The scanner modules (Step 5) are inherently network-dependent — that's
    the product. Tests using this fixture skip (rather than fail) when this
    environment has no outbound internet access, the same graceful-degrade
    pattern as `redis_client` below."""
    if not _has_internet():
        pytest.skip("No internet access in this environment.")


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis]:
    """A real Redis connection, per contract §10 rule 7 ("enforced in Redis").
    Skips (rather than fails) when Redis isn't reachable, so `pytest` degrades
    gracefully outside `docker compose exec api pytest` — the documented way
    to run the test suite (README.md), where Redis is always up."""
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis is not reachable — run via `docker compose exec api pytest`.")
    yield client
    await client.aclose()
