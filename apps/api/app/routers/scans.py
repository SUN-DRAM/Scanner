"""`POST /api/v1/scans`, `GET /api/v1/scans/{scan_id}`, and
`GET /api/v1/scans/slug/{public_slug}` (contract §7), plus the two
`.../report.pdf` PDF export endpoints (§7.14, v2.9).

This is the only place a `scans` row is created or an `arq` job is
enqueued. `app.scanner.orchestrator.run_scan` (run by the worker) is the
only place a row is ever updated after that. The PDF endpoints only ever
read a row already written by that path — no re-scan, no re-grading.
"""

from __future__ import annotations

import contextlib
import hashlib
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from arq import ArqRedis
from fastapi import APIRouter, Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.enums import ScanStatus
from app.errors import ApiException, ErrorCode
from app.models import ScanRecord
from app.pdf.cache import get_cached_pdf, set_cached_pdf
from app.pdf.filename import build_report_filename
from app.pdf.renderer import render_scan_pdf
from app.ratelimit import (
    RateLimitExceeded,
    enforce_pdf_rate_limit,
    enforce_scan_rate_limits,
)
from app.redis_client import get_arq_pool, get_redis_client
from app.safety import (
    HostnameResolutionError,
    normalize_hostname,
    resolve_and_validate,
    validate_port,
)
from app.scanner.orchestrator import EMPTY_MODULES, share_url
from app.schemas import Scan, ScanCreateRequest, ScanCreateResponse
from app.stats import increment_daily_stat

router = APIRouter(tags=["scans"])

_SLUG_LENGTH = 12
_SLUG_ALPHABET = string.ascii_letters + string.digits
_MAX_SLUG_ATTEMPTS = 8


def _generate_public_slug() -> str:
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(_SLUG_LENGTH))


def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


def _poll_url(scan_id: uuid.UUID) -> str:
    return f"/api/v1/scans/{scan_id}"


async def _find_cached_scan(
    session: AsyncSession, hostname: str, ttl_seconds: int
) -> ScanRecord | None:
    # Contract §7.1 says "the same hostname", and §11's only index over this
    # table is (hostname, created_at desc) — not (hostname, port) — so the
    # cache is deliberately keyed on hostname alone. A scan of the same host
    # on a different port within the TTL will therefore also hit this cache;
    # that is the contract's literal shape, not an oversight here.
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
    stmt = (
        select(ScanRecord)
        .where(
            ScanRecord.hostname == hostname,
            ScanRecord.status == ScanStatus.COMPLETED.value,
            ScanRecord.created_at >= cutoff,
        )
        .order_by(ScanRecord.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _create_scan_record(
    session: AsyncSession, hostname: str, port: int, client_ip: str
) -> ScanRecord:
    # Contract §11: "client_ip_hash varchar(64), -- sha256(ip + salt), never
    # the raw IP". §4 defines no salt env var to pair with that, so this
    # hashes the IP alone — still never the raw address, per CLAUDE.md rule
    # 10 — until a salt variable is added to the contract.
    ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()

    for _ in range(_MAX_SLUG_ATTEMPTS):
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=_generate_public_slug(),
            hostname=hostname,
            port=port,
            status=ScanStatus.QUEUED.value,
            client_ip_hash=ip_hash,
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


def _scan_from_record(record: ScanRecord) -> Scan:
    # A completed or failed scan always has its full result persisted as
    # JSONB (orchestrator.py) — that is the one source of truth, re-parsed
    # rather than partially reconstructed from the top-level columns. A
    # queued/running scan has no result yet, so contract §6.1's "modules may
    # be null" shape is built directly from what the row does have.
    if record.result is not None:
        return Scan.model_validate(record.result)

    return Scan(
        scan_id=str(record.scan_id),
        public_slug=record.public_slug,
        hostname=record.hostname,
        port=record.port,
        status=ScanStatus(record.status),
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        duration_ms=record.duration_ms,
        cached=False,
        overall_grade=None,
        overall_score=None,
        headline=None,
        is_complete=None,
        incomplete_modules=None,
        share_url=share_url(record),
        counts=None,
        modules=EMPTY_MODULES,
        findings=[],
        error=None,
    )


@router.post("/scans", response_model=ScanCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    payload: ScanCreateRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis_client: Redis = Depends(get_redis_client),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> ScanCreateResponse:
    settings = get_settings()

    normalized = normalize_hostname(payload.hostname, payload.port)
    validate_port(normalized.port)

    cached_record = await _find_cached_scan(
        session, normalized.hostname, settings.scan_cache_ttl_seconds
    )
    if cached_record is not None:
        response.status_code = status.HTTP_200_OK
        return ScanCreateResponse(
            scan_id=str(cached_record.scan_id),
            public_slug=cached_record.public_slug,
            status=ScanStatus(cached_record.status),
            poll_url=_poll_url(cached_record.scan_id),
            share_url=share_url(cached_record),
            cached=True,
        )

    try:
        await enforce_scan_rate_limits(
            redis_client,
            client_ip=_client_ip(request),
            hostname=normalized.hostname,
            per_ip_per_hour=settings.rate_limit_per_ip_per_hour,
            per_hostname_per_hour=settings.rate_limit_per_hostname_per_hour,
        )
    except RateLimitExceeded as exc:
        minutes = max(1, exc.retry_after_seconds // 60)
        raise ApiException(
            ErrorCode.RATE_LIMITED,
            f"Too many scans from this address. Try again in {minutes} minutes.",
            {"retry_after_seconds": exc.retry_after_seconds},
        ) from exc

    # §10 rules 1+2, applied synchronously at submission time so an obvious
    # SSRF attempt (a private/reserved target) is rejected before any row is
    # created. A hostname that simply doesn't resolve is deliberately *not*
    # handled here — §7.4 says that becomes a `failed` Scan, not an HTTP
    # error, so it falls through to the normal queued/enqueue path below and
    # the worker records the same HostnameResolutionError itself.
    with contextlib.suppress(HostnameResolutionError):
        await resolve_and_validate(normalized.hostname)

    record = await _create_scan_record(
        session, normalized.hostname, normalized.port, _client_ip(request)
    )
    await increment_daily_stat(session, "scans_started")
    await session.commit()
    await arq_pool.enqueue_job("run_scan_job", str(record.scan_id))

    response.status_code = status.HTTP_202_ACCEPTED
    return ScanCreateResponse(
        scan_id=str(record.scan_id),
        public_slug=record.public_slug,
        status=ScanStatus(record.status),
        poll_url=_poll_url(record.scan_id),
        share_url=share_url(record),
        cached=False,
    )


@router.get("/scans/{scan_id}", response_model=Scan)
async def get_scan_by_id(scan_id: str, session: AsyncSession = Depends(get_session)) -> Scan:
    try:
        parsed_id = uuid.UUID(scan_id)
    except ValueError as exc:
        raise ApiException(
            ErrorCode.SCAN_NOT_FOUND, f"No scan found for '{scan_id}'.", {"scan_id": scan_id}
        ) from exc

    record = await session.get(ScanRecord, parsed_id)
    if record is None:
        raise ApiException(
            ErrorCode.SCAN_NOT_FOUND, f"No scan found for '{scan_id}'.", {"scan_id": scan_id}
        )
    return _scan_from_record(record)


@router.get("/scans/slug/{public_slug}", response_model=Scan)
async def get_scan_by_slug(public_slug: str, session: AsyncSession = Depends(get_session)) -> Scan:
    stmt = select(ScanRecord).where(ScanRecord.public_slug == public_slug)
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise ApiException(
            ErrorCode.SCAN_NOT_FOUND,
            f"No scan found for '{public_slug}'.",
            {"public_slug": public_slug},
        )
    # The share link (contract §6.1 `share_url`) is the only thing that
    # reaches this endpoint by slug — including the submitter's own first
    # view right after creating the scan, since the frontend redirects here.
    # That's the honest count of "this share URL was opened," not a proxy
    # for a distinct third party; no session/cookie tracking exists to tell
    # the two apart, and adding one would be scope creep for a Gate B counter.
    await increment_daily_stat(session, "share_link_opens")
    await session.commit()
    return _scan_from_record(record)


async def _get_scan_record_by_id(session: AsyncSession, scan_id: str) -> ScanRecord:
    try:
        parsed_id = uuid.UUID(scan_id)
    except ValueError as exc:
        raise ApiException(
            ErrorCode.SCAN_NOT_FOUND, f"No scan found for '{scan_id}'.", {"scan_id": scan_id}
        ) from exc
    record = await session.get(ScanRecord, parsed_id)
    if record is None:
        raise ApiException(
            ErrorCode.SCAN_NOT_FOUND, f"No scan found for '{scan_id}'.", {"scan_id": scan_id}
        )
    return record


async def _get_scan_record_by_slug(session: AsyncSession, public_slug: str) -> ScanRecord:
    stmt = select(ScanRecord).where(ScanRecord.public_slug == public_slug)
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise ApiException(
            ErrorCode.SCAN_NOT_FOUND,
            f"No scan found for '{public_slug}'.",
            {"public_slug": public_slug},
        )
    return record


async def _serve_report_pdf(
    record: ScanRecord, request: Request, redis_client: Redis
) -> Response:
    """Shared by both `.../report.pdf` routes below (contract §7.14, v2.9):
    same lookup semantics as the plain scan-GET pair, same `404
    SCAN_NOT_FOUND` (raised by the caller before this is reached), plus the
    export-specific rules — `409` on a non-completed scan, its own rate
    limit, and the Redis cache. Deliberately does **not** call
    `increment_daily_stat("share_link_opens", ...)` even when reached via the
    slug route — that counter means "the shareable HTML page was opened,"
    not "a PDF was downloaded," and a browser never navigates here."""
    if record.status != ScanStatus.COMPLETED.value:
        raise ApiException(
            ErrorCode.REPORT_NOT_AVAILABLE,
            "This report isn't ready yet. It's only available once the scan completes.",
            {"scan_id": str(record.scan_id), "status": record.status},
        )

    scan_id = str(record.scan_id)
    settings = get_settings()

    # Cache check first, same precedent as POST /scans's cached-scan path
    # (a cache hit never touches the rate limiter) — a shared link posted in
    # a WhatsApp/Slack group must not let its own popularity trip the limit
    # for the people opening it.
    cached = await get_cached_pdf(redis_client, scan_id)
    if cached is not None:
        pdf_bytes = cached
    else:
        try:
            await enforce_pdf_rate_limit(
                redis_client,
                client_ip=_client_ip(request),
                per_ip_per_hour=settings.rate_limit_pdf_per_ip_per_hour,
            )
        except RateLimitExceeded as exc:
            minutes = max(1, exc.retry_after_seconds // 60)
            raise ApiException(
                ErrorCode.RATE_LIMITED,
                f"Too many report downloads from this address. Try again in {minutes} minutes.",
                {"retry_after_seconds": exc.retry_after_seconds},
            ) from exc

        scan = _scan_from_record(record)
        pdf_bytes = await render_scan_pdf(scan)
        await set_cached_pdf(redis_client, scan_id, pdf_bytes, settings.pdf_cache_ttl_seconds)

    filename = build_report_filename(record.hostname, record.completed_at or record.created_at)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/scans/{scan_id}/report.pdf")
async def get_scan_report_pdf(
    scan_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis_client: Redis = Depends(get_redis_client),
) -> Response:
    record = await _get_scan_record_by_id(session, scan_id)
    return await _serve_report_pdf(record, request, redis_client)


@router.get("/scans/slug/{public_slug}/report.pdf")
async def get_scan_report_pdf_by_slug(
    public_slug: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis_client: Redis = Depends(get_redis_client),
) -> Response:
    record = await _get_scan_record_by_slug(session, public_slug)
    return await _serve_report_pdf(record, request, redis_client)
