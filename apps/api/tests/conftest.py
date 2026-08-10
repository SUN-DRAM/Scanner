"""Shared pytest fixtures."""

from __future__ import annotations

import socket
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base


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


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """A real Postgres connection against the contract §11 schema. Skips
    (rather than fails) when Postgres isn't reachable, the same
    graceful-degrade pattern as `redis_client` above — the DB-backed request
    handlers (Step 6) are exercised via `docker compose exec api pytest`."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        await engine.dispose()
        pytest.skip("Postgres is not reachable — run via `docker compose exec api pytest`.")

    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


class FakeArqPool:
    """Stands in for the arq connection pool in router tests: records what
    was enqueued without needing a running arq worker, since job *execution*
    is `run_scan`'s concern and already covered by test_orchestrator.py."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, function: str, *args: Any, **_kwargs: Any) -> None:
        self.enqueued.append((function, args))


@pytest.fixture
def fake_arq_pool() -> FakeArqPool:
    return FakeArqPool()
