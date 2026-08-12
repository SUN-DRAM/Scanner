"""Anonymous daily usage counters (Gate B item 2). One upserted row per UTC
day in `daily_stats` — no personal data, just five running totals.

Callers pass an already-open session and are responsible for committing it
(same convention as `orchestrator.py` and `routers/scans.py`) so a counter
increment always lands in the same transaction as the state change it's
counting, never as a separate, potentially-lost write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyStatsRecord

DailyStatField = Literal[
    "scans_started",
    "scans_completed",
    "scans_failed",
    "share_link_opens",
    "waitlist_signups",
]


async def increment_daily_stat(
    session: AsyncSession, field: DailyStatField, *, when: datetime | None = None
) -> None:
    day = (when or datetime.now(UTC)).date()
    column = DailyStatsRecord.__table__.c[field]
    stmt = insert(DailyStatsRecord).values(day=day, **{field: 1})
    stmt = stmt.on_conflict_do_update(index_elements=["day"], set_={field: column + 1})
    await session.execute(stmt)
