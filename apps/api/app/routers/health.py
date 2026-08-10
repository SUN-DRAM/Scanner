"""Liveness + dependency health check."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

router = APIRouter(tags=["health"])

DependencyStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: DependencyStatus
    redis: DependencyStatus
    version: str
    checked_at: str


async def _check_database() -> DependencyStatus:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"
    finally:
        await engine.dispose()


async def _check_redis() -> DependencyStatus:
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
    try:
        await client.ping()
        return "ok"
    except Exception:
        return "error"
    finally:
        await client.aclose()


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    database_status = await _check_database()
    redis_status = await _check_redis()
    overall: Literal["ok", "degraded"] = (
        "ok" if database_status == "ok" and redis_status == "ok" else "degraded"
    )
    return HealthResponse(
        status=overall,
        database=database_status,
        redis=redis_status,
        version="1.0.0",
        checked_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
