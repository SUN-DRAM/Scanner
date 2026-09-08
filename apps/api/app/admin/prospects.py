"""`/api/v1/admin/prospects*` (contract §7.13) — bulk-scan an agency's
client portfolio before an outreach email, grouped under a label.

These scans are **not** monitored hostnames: they belong to no org, they
never schedule, they never alert. Each accepted hostname is an ordinary
`scans` row (same engine path) with `monitor_id` null, linked to its batch
only through `prospect_scans` — so a prospect scan can never leak into a
customer's dashboard, and it is excluded from `daily_stats` and the §7.13
funnel.
"""

from __future__ import annotations

import contextlib
import secrets
import string
import uuid
from typing import Any

from arq import ArqRedis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Grade, ScanStatus
from app.errors import ApiException, ErrorCode
from app.models import ProspectBatchRecord, ProspectScanRecord, ScanRecord
from app.safety import (
    HostnameResolutionError,
    normalize_hostname,
    resolve_and_validate,
    validate_port,
)
from app.scanner.orchestrator import share_url
from app.schemas import (
    AdminProspectBatchDetail,
    AdminProspectBatchRow,
    AdminProspectItem,
    PaginatedList,
)

_SLUG_LENGTH = 12
_SLUG_ALPHABET = string.ascii_letters + string.digits
_MAX_SLUG_ATTEMPTS = 8
_EXPIRING_SOON_DAYS = 60
_LONG_LIFETIME_DAYS = 200
_GRADE_ORDER: tuple[str, ...] = ("A+", "A", "B", "C", "D", "E", "F")
_PENDING_STATES = (ScanStatus.QUEUED.value, ScanStatus.RUNNING.value)


def _generate_slug() -> str:
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(_SLUG_LENGTH))


def _grade_or_none(value: str | None) -> Grade | None:
    try:
        return Grade(value) if value else None
    except ValueError:
        return None


def _grade_rank(grade: Grade | None) -> int | None:
    return _GRADE_ORDER.index(grade.value) if grade is not None else None


def _not_found(batch_id: str) -> ApiException:
    return ApiException(ErrorCode.NOT_FOUND, "No prospect batch found.", {"batch_id": batch_id})


def _cert_facts(result: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """`(days_until_expiry, lifetime_days)` from a completed scan's stored
    certificate module data (§6.4), or `(None, None)`."""
    if not result:
        return None, None
    modules = result.get("modules") or {}
    certificate = modules.get("certificate") or {}
    data = certificate.get("data") or {}
    if not isinstance(data, dict):
        return None, None
    days = data.get("days_until_expiry")
    lifetime = data.get("lifetime_days")
    return (
        days if isinstance(days, int) else None,
        lifetime if isinstance(lifetime, int) else None,
    )


async def _create_prospect_scan_record(
    session: AsyncSession, hostname: str, port: int
) -> ScanRecord:
    """A queued `scans` row for a prospect scan — `monitor_id` null,
    `client_ip_hash` null (nothing to hash — an operator action, not a
    request from the public), cache deliberately bypassed. Same
    public_slug collision-retry (commit per attempt) as
    `app/monitors.py`'s `create_monitor_scan_record`."""
    for _ in range(_MAX_SLUG_ATTEMPTS):
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=_generate_slug(),
            hostname=hostname,
            port=port,
            status=ScanStatus.QUEUED.value,
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(record)
        return record

    raise ApiException(
        ErrorCode.INTERNAL_ERROR, "Could not allocate a unique share link. Try again."
    )


def _rejected_item(hostname: str, code: ErrorCode) -> AdminProspectItem:
    return AdminProspectItem(
        hostname=hostname,
        accepted=False,
        reason_code=code,
        scan_id=None,
        public_slug=None,
        share_url=None,
        status=None,
        grade=None,
        days_to_expiry=None,
        cert_lifetime_days=None,
    )


async def create_prospect_batch(
    session: AsyncSession,
    arq_pool: ArqRedis,
    *,
    label: str,
    hostnames: list[str],
) -> AdminProspectBatchDetail:
    batch = ProspectBatchRecord(batch_id=uuid.uuid4(), label=label)
    session.add(batch)
    await session.commit()

    rejected: list[AdminProspectItem] = []
    seen: set[tuple[str, int]] = set()
    enqueue: list[uuid.UUID] = []

    for raw in hostnames:
        try:
            normalized = normalize_hostname(raw, None)
            validate_port(normalized.port)
            # §10 rules 1+2, synchronous like POST /scans: reject an obvious
            # SSRF target now. An unresolvable hostname is still accepted —
            # the worker reports it, the same treatment a public scan gets.
            with contextlib.suppress(HostnameResolutionError):
                await resolve_and_validate(normalized.hostname)
        except ApiException as exc:
            rejected.append(_rejected_item(raw, exc.code))
            continue

        key = (normalized.hostname, normalized.port)
        if key in seen:
            rejected.append(_rejected_item(raw, ErrorCode.DUPLICATE_HOSTNAME))
            continue
        seen.add(key)

        scan = await _create_prospect_scan_record(session, normalized.hostname, normalized.port)
        session.add(
            ProspectScanRecord(
                id=uuid.uuid4(),
                batch_id=batch.batch_id,
                scan_id=scan.scan_id,
                hostname=normalized.hostname,
            )
        )
        await session.commit()
        enqueue.append(scan.scan_id)

    for scan_id in enqueue:
        await arq_pool.enqueue_job("run_scan_job", str(scan_id))

    detail = await get_prospect_batch_detail(session, str(batch.batch_id))
    return detail.model_copy(update={"items": [*detail.items, *rejected]})


async def _build_detail(
    session: AsyncSession, batch: ProspectBatchRecord
) -> AdminProspectBatchDetail:
    rows = (
        await session.execute(
            select(ProspectScanRecord, ScanRecord)
            .join(ScanRecord, ScanRecord.scan_id == ProspectScanRecord.scan_id)
            .where(ProspectScanRecord.batch_id == batch.batch_id)
            .order_by(ProspectScanRecord.created_at.asc())
        )
    ).all()

    items: list[AdminProspectItem] = []
    completed = 0
    pending = 0
    worst_rank: int | None = None
    expiring = 0
    long_lifetime = 0

    for link, scan in rows:
        days, lifetime = _cert_facts(scan.result)
        grade = _grade_or_none(scan.overall_grade)
        if scan.status == ScanStatus.COMPLETED.value:
            completed += 1
        elif scan.status in _PENDING_STATES:
            pending += 1
        rank = _grade_rank(grade)
        if rank is not None:
            worst_rank = rank if worst_rank is None else max(worst_rank, rank)
        if days is not None and days <= _EXPIRING_SOON_DAYS:
            expiring += 1
        if lifetime is not None and lifetime > _LONG_LIFETIME_DAYS:
            long_lifetime += 1

        items.append(
            AdminProspectItem(
                hostname=link.hostname,
                accepted=True,
                reason_code=None,
                scan_id=str(scan.scan_id),
                public_slug=scan.public_slug,
                share_url=share_url(scan),
                status=ScanStatus(scan.status),
                grade=grade,
                days_to_expiry=days,
                cert_lifetime_days=lifetime,
            )
        )

    return AdminProspectBatchDetail(
        batch_id=str(batch.batch_id),
        label=batch.label,
        created_at=batch.created_at,
        hostname_count=len(rows),
        scans_completed=completed,
        scans_pending=pending,
        worst_grade=Grade(_GRADE_ORDER[worst_rank]) if worst_rank is not None else None,
        expiring_60d_count=expiring,
        over_200day_lifetime_count=long_lifetime,
        items=items,
    )


async def _load_batch(session: AsyncSession, batch_id: str) -> ProspectBatchRecord:
    try:
        parsed = uuid.UUID(batch_id)
    except ValueError as exc:
        raise _not_found(batch_id) from exc
    batch = await session.get(ProspectBatchRecord, parsed)
    if batch is None:
        raise _not_found(batch_id)
    return batch


async def get_prospect_batch_detail(
    session: AsyncSession, batch_id: str
) -> AdminProspectBatchDetail:
    return await _build_detail(session, await _load_batch(session, batch_id))


def _detail_to_row(detail: AdminProspectBatchDetail) -> AdminProspectBatchRow:
    return AdminProspectBatchRow(
        batch_id=detail.batch_id,
        label=detail.label,
        created_at=detail.created_at,
        hostname_count=detail.hostname_count,
        scans_completed=detail.scans_completed,
        scans_pending=detail.scans_pending,
        worst_grade=detail.worst_grade,
        expiring_60d_count=detail.expiring_60d_count,
        over_200day_lifetime_count=detail.over_200day_lifetime_count,
    )


async def list_prospect_batches(
    session: AsyncSession, *, page: int, per_page: int
) -> PaginatedList[AdminProspectBatchRow]:
    total = (
        await session.execute(select(func.count()).select_from(ProspectBatchRecord))
    ).scalar_one()
    batches = (
        (
            await session.execute(
                select(ProspectBatchRecord)
                .order_by(ProspectBatchRecord.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    items = [_detail_to_row(await _build_detail(session, batch)) for batch in batches]
    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )


def _slugify_label(label: str) -> str:
    kept = [c.lower() if c.isalnum() else "-" for c in label]
    slug = "".join(kept).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "batch"


async def prospect_batch_csv(session: AsyncSession, batch_id: str) -> tuple[str, str]:
    """Returns `(csv_text, filename)`. Columns: label, hostname, grade,
    days_to_expiry, cert_lifetime_days, share_url (§7.13)."""
    detail = await _build_detail(session, await _load_batch(session, batch_id))

    lines = ["label,hostname,grade,days_to_expiry,cert_lifetime_days,share_url"]
    for item in detail.items:
        lines.append(
            ",".join(
                [
                    _csv_cell(detail.label),
                    _csv_cell(item.hostname),
                    _csv_cell(item.grade.value if item.grade else ""),
                    _csv_cell("" if item.days_to_expiry is None else str(item.days_to_expiry)),
                    _csv_cell(
                        "" if item.cert_lifetime_days is None else str(item.cert_lifetime_days)
                    ),
                    _csv_cell(item.share_url or ""),
                ]
            )
        )
    return "\n".join(lines) + "\n", f"prospects-{_slugify_label(detail.label)}.csv"


def _csv_cell(value: str) -> str:
    if any(ch in value for ch in [",", '"', "\n"]):
        return '"' + value.replace('"', '""') + '"'
    return value
