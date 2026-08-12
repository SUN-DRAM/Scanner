"""`GET /api/v1/admin/stats` (contract §7.5, Gate B item 3).

Not a dashboard — a plain-text table, gated by a single shared token in
`ADMIN_TOKEN`. Deliberately outside the JSON API surface: this is meant to
be opened directly in a browser (`.../admin/stats?token=...`), not consumed
by the frontend, so `text/plain` is the honest content type rather than
JSON dressed up for humans.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import DailyStatsRecord, ScanRecord

router = APIRouter(tags=["admin"])

_STATS_DAYS = 30
_RECENT_SCANS_LIMIT = 100


def _authorized(token: str | None) -> bool:
    configured = get_settings().admin_token
    if not configured or not token:
        return False
    return secrets.compare_digest(token, configured)


def _forbidden() -> Response:
    return Response(content="Forbidden\n", status_code=403, media_type="text/plain")


@router.get("/admin/stats")
async def admin_stats(
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not _authorized(token):
        return _forbidden()

    stats_stmt = (
        select(DailyStatsRecord).order_by(DailyStatsRecord.day.desc()).limit(_STATS_DAYS)
    )
    stats_rows = (await session.execute(stats_stmt)).scalars().all()

    scans_stmt = (
        select(ScanRecord)
        .order_by(ScanRecord.created_at.desc())
        .limit(_RECENT_SCANS_LIMIT)
    )
    scan_rows = (await session.execute(scans_stmt)).scalars().all()

    lines: list[str] = []
    lines.append("SUN-DRAM Scanner — admin stats")
    lines.append("")
    lines.append(f"Daily stats (last {_STATS_DAYS} days)")
    lines.append(
        f"{'day':<12}{'started':>9}{'completed':>11}{'failed':>8}{'share_opens':>13}{'waitlist':>10}"
    )
    for row in stats_rows:
        lines.append(
            f"{row.day.isoformat():<12}{row.scans_started:>9}{row.scans_completed:>11}"
            f"{row.scans_failed:>8}{row.share_link_opens:>13}{row.waitlist_signups:>10}"
        )
    if not stats_rows:
        lines.append("(no data yet)")

    lines.append("")
    lines.append(f"Last {_RECENT_SCANS_LIMIT} scanned hostnames")
    lines.append(f"{'created_at':<22}{'status':<11}{'grade':<7}hostname")
    for record in scan_rows:
        grade = record.overall_grade or "-"
        created = record.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f"{created:<22}{record.status:<11}{grade:<7}{record.hostname}")
    if not scan_rows:
        lines.append("(no scans yet)")

    return Response(content="\n".join(lines) + "\n", media_type="text/plain")
