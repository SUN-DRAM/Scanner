"""The internal admin surface (contract §7.5 and §7.13).

`GET /api/v1/admin/stats` (§7.5, Gate B) stays a plain-text table gated by
`?token=`. Everything else here is the v2.8 dashboard: JSON, gated by the
`X-Admin-Token` header (`?token=` also accepted), read-only except the
prospect routes (a later step), and never touching a customer-owned table.
"""

from __future__ import annotations

import secrets
from datetime import date
from typing import Literal

from arq import ArqRedis
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.accounts import list_account_rows
from app.admin.auth import require_admin_token
from app.admin.detail import build_account_detail
from app.admin.funnel import build_funnel_report
from app.admin.ops import build_health_report
from app.admin.prospects import (
    create_prospect_batch,
    get_prospect_batch_detail,
    list_prospect_batches,
    prospect_batch_csv,
)
from app.config import get_settings
from app.db import get_session
from app.enums import AccountHealth, OutreachProspectState, PlanCode
from app.models import DailyStatsRecord, ScanRecord
from app.outreach.admin import (
    create_campaign,
    get_campaign,
    get_scan_progress,
    import_campaign_csv,
    list_campaigns,
    list_prospects,
    pause_scan,
    resume_scan,
    start_scan,
)
from app.redis_client import get_arq_pool, get_redis_client
from app.schemas import (
    AdminAccountDetail,
    AdminAccountRow,
    AdminFunnelReport,
    AdminHealthReport,
    AdminProspectBatchDetail,
    AdminProspectBatchRow,
    OutreachCampaign,
    OutreachCampaignCreateRequest,
    OutreachCampaignRow,
    OutreachImportReport,
    OutreachProspectRow,
    OutreachScanProgress,
    PaginatedList,
    ProspectBatchCreateRequest,
)

router = APIRouter(tags=["admin"])

_STATS_DAYS = 30
_RECENT_SCANS_LIMIT = 100
_ADMIN_MAX_PER_PAGE = 100  # contract §6.14


# --- §7.5 GET /api/v1/admin/stats (Gate B, unchanged) ---


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

    stats_stmt = select(DailyStatsRecord).order_by(DailyStatsRecord.day.desc()).limit(_STATS_DAYS)
    stats_rows = (await session.execute(stats_stmt)).scalars().all()

    scans_stmt = (
        select(ScanRecord).order_by(ScanRecord.created_at.desc()).limit(_RECENT_SCANS_LIMIT)
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


# --- §7.13 admin dashboard (v2.8) ---


@router.get(
    "/admin/accounts",
    response_model=PaginatedList[AdminAccountRow],
    dependencies=[Depends(require_admin_token)],
)
async def admin_accounts(
    session: AsyncSession = Depends(get_session),
    plan: PlanCode | None = Query(default=None),
    health: AccountHealth | None = Query(default=None),
    signed_up_after: date | None = Query(default=None),
    signed_up_before: date | None = Query(default=None),
    sort: Literal["newest", "oldest", "last_login", "soonest_expiry"] = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_ADMIN_MAX_PER_PAGE),
) -> PaginatedList[AdminAccountRow]:
    items, total = await list_account_rows(
        session,
        plan=plan,
        health=health,
        signed_up_after=signed_up_after,
        signed_up_before=signed_up_before,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )


@router.get(
    "/admin/accounts/{org_id}",
    response_model=AdminAccountDetail,
    dependencies=[Depends(require_admin_token)],
)
async def admin_account_detail(
    org_id: str,
    session: AsyncSession = Depends(get_session),
) -> AdminAccountDetail:
    return await build_account_detail(session, org_id)


@router.get(
    "/admin/health",
    response_model=AdminHealthReport,
    dependencies=[Depends(require_admin_token)],
)
async def admin_health(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis_client),
) -> AdminHealthReport:
    return await build_health_report(session, redis)


@router.get(
    "/admin/funnel",
    response_model=AdminFunnelReport,
    dependencies=[Depends(require_admin_token)],
)
async def admin_funnel(
    session: AsyncSession = Depends(get_session),
) -> AdminFunnelReport:
    return await build_funnel_report(session)


@router.get(
    "/admin/prospects",
    response_model=PaginatedList[AdminProspectBatchRow],
    dependencies=[Depends(require_admin_token)],
)
async def admin_list_prospects(
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_ADMIN_MAX_PER_PAGE),
) -> PaginatedList[AdminProspectBatchRow]:
    return await list_prospect_batches(session, page=page, per_page=per_page)


@router.post(
    "/admin/prospects",
    response_model=AdminProspectBatchDetail,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_token)],
)
async def admin_create_prospect_batch(
    payload: ProspectBatchCreateRequest,
    session: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> AdminProspectBatchDetail:
    return await create_prospect_batch(
        session, arq_pool, label=payload.label, hostnames=payload.hostnames
    )


@router.get(
    "/admin/prospects/{batch_id}",
    response_model=AdminProspectBatchDetail,
    dependencies=[Depends(require_admin_token)],
)
async def admin_prospect_batch_detail(
    batch_id: str,
    session: AsyncSession = Depends(get_session),
) -> AdminProspectBatchDetail:
    return await get_prospect_batch_detail(session, batch_id)


@router.get("/admin/prospects/{batch_id}/export", dependencies=[Depends(require_admin_token)])
async def admin_prospect_batch_export(
    batch_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    csv_text, filename = await prospect_batch_csv(session, batch_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- §7.15 Outreach orchestrator, Stage 1 (v3.6) ---


@router.post(
    "/admin/outreach/campaigns",
    response_model=OutreachCampaign,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_token)],
)
async def admin_create_outreach_campaign(
    payload: OutreachCampaignCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> OutreachCampaign:
    return await create_campaign(session, name=payload.name)


@router.get(
    "/admin/outreach/campaigns",
    response_model=PaginatedList[OutreachCampaignRow],
    dependencies=[Depends(require_admin_token)],
)
async def admin_list_outreach_campaigns(
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_ADMIN_MAX_PER_PAGE),
) -> PaginatedList[OutreachCampaignRow]:
    return await list_campaigns(session, page=page, per_page=per_page)


@router.get(
    "/admin/outreach/campaigns/{campaign_id}",
    response_model=OutreachCampaignRow,
    dependencies=[Depends(require_admin_token)],
)
async def admin_get_outreach_campaign(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
) -> OutreachCampaignRow:
    return await get_campaign(session, campaign_id)


@router.post(
    "/admin/outreach/campaigns/{campaign_id}/import",
    response_model=OutreachImportReport,
    dependencies=[Depends(require_admin_token)],
)
async def admin_import_outreach_campaign_csv(
    campaign_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> OutreachImportReport:
    csv_bytes = await file.read()
    return await import_campaign_csv(session, campaign_id, csv_bytes)


@router.get(
    "/admin/outreach/campaigns/{campaign_id}/prospects",
    response_model=PaginatedList[OutreachProspectRow],
    dependencies=[Depends(require_admin_token)],
)
async def admin_list_outreach_prospects(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
    state: OutreachProspectState | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_ADMIN_MAX_PER_PAGE),
) -> PaginatedList[OutreachProspectRow]:
    return await list_prospects(session, campaign_id, state=state, page=page, per_page=per_page)


# --- §7.16 Outreach orchestrator, Stage 2 batch control (v3.9/v3.10) ---


@router.post(
    "/admin/outreach/campaigns/{campaign_id}/scan",
    response_model=OutreachCampaignRow,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_token)],
)
async def admin_start_outreach_scan(
    campaign_id: str,
    include_weak: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> OutreachCampaignRow:
    return await start_scan(session, campaign_id, include_weak=include_weak)


@router.post(
    "/admin/outreach/campaigns/{campaign_id}/pause",
    response_model=OutreachCampaignRow,
    dependencies=[Depends(require_admin_token)],
)
async def admin_pause_outreach_scan(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
) -> OutreachCampaignRow:
    return await pause_scan(session, campaign_id)


@router.post(
    "/admin/outreach/campaigns/{campaign_id}/resume",
    response_model=OutreachCampaignRow,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_token)],
)
async def admin_resume_outreach_scan(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
) -> OutreachCampaignRow:
    return await resume_scan(session, campaign_id)


@router.get(
    "/admin/outreach/campaigns/{campaign_id}/scan-progress",
    response_model=OutreachScanProgress,
    dependencies=[Depends(require_admin_token)],
)
async def admin_outreach_scan_progress(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
) -> OutreachScanProgress:
    return await get_scan_progress(session, campaign_id)
