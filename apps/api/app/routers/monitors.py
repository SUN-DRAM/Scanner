"""GET/POST /api/v1/monitors, GET/PATCH/DELETE /api/v1/monitors/{monitor_id},
POST /api/v1/monitors/bulk, POST /api/v1/monitors/{monitor_id}/scan
(contract §7.8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from arq import ArqRedis
from fastapi import APIRouter, Depends, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentOrgContext, get_current_org_context, require_roles
from app.enums import MonitorState, ScanStatus, UserRole
from app.errors import ApiException, ErrorCode
from app.models import MonitoredHostnameRecord
from app.monitors import (
    compute_days_until_expiry,
    count_quota_monitors,
    create_manual_rescan,
    create_monitor,
)
from app.ratelimit import RateLimitExceeded, enforce_monitor_scan_rate_limit
from app.redis_client import get_arq_pool, get_redis_client
from app.scanner.orchestrator import share_url
from app.schemas import (
    MonitorBulkRequest,
    MonitorBulkResponse,
    MonitorBulkRow,
    MonitorCreateRequest,
    MonitoredHostname,
    MonitorUpdateRequest,
    PaginatedList,
    ScanCreateResponse,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])

_MAX_PER_PAGE = 100  # contract §6.14
# Module-level singleton, not `Depends(require_roles(...))` inline at each
# call site — see routers/orgs.py's identical comment on the same ruff B008
# tradeoff.
_require_manage_monitors = require_roles(UserRole.OWNER, UserRole.ADMIN)


def _monitor_to_schema(record: MonitoredHostnameRecord) -> MonitoredHostname:
    return MonitoredHostname(
        monitor_id=str(record.monitor_id),
        org_id=str(record.org_id),
        hostname=record.hostname,
        port=record.port,
        state=MonitorState(record.state),
        label=record.label,
        notes=record.notes,
        last_scan_id=str(record.last_scan_id) if record.last_scan_id else None,
        last_grade=record.last_grade,  # type: ignore[arg-type]
        last_score=record.last_score,
        last_scanned_at=record.last_scanned_at,
        next_scan_at=record.next_scan_at,
        days_until_expiry=compute_days_until_expiry(record.cert_not_after),
        created_at=record.created_at,
    )


async def _get_org_monitor(
    session: AsyncSession, org_id: uuid.UUID, monitor_id: str
) -> MonitoredHostnameRecord:
    try:
        parsed_id = uuid.UUID(monitor_id)
    except ValueError as exc:
        raise ApiException(
            ErrorCode.NOT_FOUND, "No monitor found.", {"monitor_id": monitor_id}
        ) from exc

    record = await session.get(MonitoredHostnameRecord, parsed_id)
    # Cross-org id (§7.6): a monitor_id belonging to a DIFFERENT org must
    # look identical to one that doesn't exist at all — 404, never 403.
    if record is None or record.org_id != org_id:
        raise ApiException(ErrorCode.NOT_FOUND, "No monitor found.", {"monitor_id": monitor_id})
    return record


@router.get("", response_model=PaginatedList[MonitoredHostname])
async def list_monitors(
    context: CurrentOrgContext = Depends(get_current_org_context),
    session: AsyncSession = Depends(get_session),
    state: MonitorState | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_MAX_PER_PAGE),
) -> PaginatedList[MonitoredHostname]:
    base_stmt = select(MonitoredHostnameRecord).where(
        MonitoredHostnameRecord.org_id == context.org.org_id
    )
    if state is not None:
        base_stmt = base_stmt.where(MonitoredHostnameRecord.state == state.value)

    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    # §7.8: always ordered by days_until_expiry ascending, nulls last —
    # equivalent to ordering by the underlying cert_not_after timestamp,
    # which is what days_until_expiry is derived from.
    stmt = (
        base_stmt.order_by(MonitoredHostnameRecord.cert_not_after.asc().nullslast())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [_monitor_to_schema(record) for record in rows]

    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )


@router.post("", response_model=MonitoredHostname, status_code=status.HTTP_201_CREATED)
async def create_monitor_endpoint(
    payload: MonitorCreateRequest,
    context: CurrentOrgContext = Depends(_require_manage_monitors),
    session: AsyncSession = Depends(get_session),
) -> MonitoredHostname:
    quota_count = await count_quota_monitors(session, context.org.org_id)
    record = await create_monitor(
        session,
        context.org,
        raw_hostname=payload.hostname,
        requested_port=payload.port,
        label=payload.label,
        notes=payload.notes,
        current_quota_count=quota_count,
    )
    return _monitor_to_schema(record)


@router.get("/{monitor_id}", response_model=MonitoredHostname)
async def get_monitor(
    monitor_id: str,
    context: CurrentOrgContext = Depends(get_current_org_context),
    session: AsyncSession = Depends(get_session),
) -> MonitoredHostname:
    record = await _get_org_monitor(session, context.org.org_id, monitor_id)
    return _monitor_to_schema(record)


@router.patch("/{monitor_id}", response_model=MonitoredHostname)
async def update_monitor(
    monitor_id: str,
    payload: MonitorUpdateRequest,
    context: CurrentOrgContext = Depends(_require_manage_monitors),
    session: AsyncSession = Depends(get_session),
) -> MonitoredHostname:
    record = await _get_org_monitor(session, context.org.org_id, monitor_id)

    # Only the keys actually present in the request are applied (§7.8) —
    # `model_fields_set` distinguishes "omitted" from "sent as null".
    fields_set = payload.model_fields_set
    if "label" in fields_set:
        record.label = payload.label
    if "notes" in fields_set:
        record.notes = payload.notes
    if "state" in fields_set and payload.state is not None:
        record.state = payload.state
        # Pausing stops the Step 4 scheduler from ever picking this monitor
        # up again until it's resumed; resuming makes it due immediately,
        # the same convention a brand-new monitor gets (app/monitors.py).
        record.next_scan_at = datetime.now(UTC) if payload.state == "active" else None

    await session.commit()
    await session.refresh(record)
    return _monitor_to_schema(record)


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_monitor(
    monitor_id: str,
    context: CurrentOrgContext = Depends(_require_manage_monitors),
    session: AsyncSession = Depends(get_session),
) -> None:
    record = await _get_org_monitor(session, context.org.org_id, monitor_id)
    await session.delete(record)
    await session.commit()


@router.post("/bulk", response_model=MonitorBulkResponse)
async def bulk_create_monitors(
    payload: MonitorBulkRequest,
    context: CurrentOrgContext = Depends(_require_manage_monitors),
    session: AsyncSession = Depends(get_session),
) -> MonitorBulkResponse:
    # Threaded through and incremented locally rather than re-queried every
    # row (§7.8: quota applies per row, in order, within one batch).
    quota_count = await count_quota_monitors(session, context.org.org_id)

    results: list[MonitorBulkRow] = []
    accepted_count = 0
    rejected_count = 0

    for raw_hostname in payload.hostnames:
        try:
            record = await create_monitor(
                session,
                context.org,
                raw_hostname=raw_hostname,
                requested_port=None,
                label=None,
                notes=None,
                current_quota_count=quota_count,
            )
        except ApiException as exc:
            rejected_count += 1
            results.append(
                MonitorBulkRow(
                    hostname=raw_hostname,
                    accepted=False,
                    monitor=None,
                    reason_code=exc.code,
                    reason=exc.message,
                )
            )
            continue

        accepted_count += 1
        quota_count += 1
        results.append(
            MonitorBulkRow(
                hostname=raw_hostname,
                accepted=True,
                monitor=_monitor_to_schema(record),
                reason_code=None,
                reason=None,
            )
        )

    return MonitorBulkResponse(
        results=results, accepted_count=accepted_count, rejected_count=rejected_count
    )


@router.post(
    "/{monitor_id}/scan", response_model=ScanCreateResponse, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_manual_scan(
    monitor_id: str,
    request: Request,
    context: CurrentOrgContext = Depends(_require_manage_monitors),
    session: AsyncSession = Depends(get_session),
    redis_client: Redis = Depends(get_redis_client),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> ScanCreateResponse:
    record = await _get_org_monitor(session, context.org.org_id, monitor_id)

    try:
        await enforce_monitor_scan_rate_limit(redis_client, monitor_id=str(record.monitor_id))
    except RateLimitExceeded as exc:
        minutes = max(1, exc.retry_after_seconds // 60)
        raise ApiException(
            ErrorCode.RATE_LIMITED,
            f"A re-scan was already triggered recently. Try again in {minutes} minutes.",
            {"retry_after_seconds": exc.retry_after_seconds},
        ) from exc

    client_ip = request.client.host if request.client is not None else "unknown"
    scan_record = await create_manual_rescan(session, record, client_ip=client_ip)
    await arq_pool.enqueue_job("run_scan_job", str(scan_record.scan_id))

    return ScanCreateResponse(
        scan_id=str(scan_record.scan_id),
        public_slug=scan_record.public_slug,
        status=ScanStatus(scan_record.status),
        poll_url=f"/api/v1/scans/{scan_record.scan_id}",
        share_url=share_url(scan_record),
        # A manual re-scan always bypasses the scan cache (§7.8) — that's
        # the whole point of the button — so this is never true.
        cached=False,
    )
