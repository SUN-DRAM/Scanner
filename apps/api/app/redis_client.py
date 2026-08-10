"""Cached Redis client (rate limiting, §10 rule 7) and the arq connection
pool used to enqueue scan jobs (§3.2 `worker.py`). Both are process-wide
singletons, created lazily on first use rather than at import time.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import cast

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    return cast(Redis, Redis.from_url(get_settings().redis_url))


_arq_pool: ArqRedis | None = None
_arq_pool_lock = asyncio.Lock()


async def get_arq_pool() -> ArqRedis:
    """FastAPI dependency: the arq pool used by `routers/scans.py` to enqueue
    `run_scan_job`. `create_pool` pings Redis, so it must be awaited — hence
    a lock-guarded lazy singleton rather than an `lru_cache`d sync function."""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    async with _arq_pool_lock:
        if _arq_pool is None:
            _arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
