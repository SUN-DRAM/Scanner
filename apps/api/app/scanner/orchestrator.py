"""Runs all seven scan modules, assembles the `Scan` object, grades it, and
persists the result.

Called by the arq worker (Step 6) once a job is dequeued. The `scans` row
must already exist with status "queued" (created by the POST handler) —
this only ever updates that row, never inserts one.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import ModuleName, ScanStatus, Severity
from app.errors import ApiError, ApiException, ErrorCode
from app.grading import ModuleScoreInput, grade_scan
from app.models import ScanRecord
from app.safety import HostnameResolutionError, resolve_and_validate
from app.scanner import (
    ScanContext,
    certificate,
    chain,
    dns_records,
    email_auth,
    headers,
    readiness,
    tls,
)
from app.schemas import (
    CertificateData,
    ModuleResult,
    Modules,
    ReadinessData,
    Scan,
    SeverityCounts,
)
from app.stats import increment_daily_stat

logger = logging.getLogger("app.scanner.orchestrator")

# Public: reused by routers/scans.py (Step 6) for the queued/running Scan
# shape and the share_url, so there is exactly one place either is built.
EMPTY_MODULES = Modules(
    certificate=None,
    chain=None,
    tls=None,
    dns=None,
    email_auth=None,
    headers=None,
    readiness=None,
)


def share_url(record: ScanRecord) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/scan/{record.public_slug}"


async def _run_certificate_then_readiness(
    ctx: ScanContext,
) -> tuple[ModuleResult[CertificateData], ModuleResult[ReadinessData]]:
    # Readiness synthesizes what certificate.py already found rather than
    # re-probing independently — see readiness.py's module docstring. Every
    # other module is genuinely independent and runs alongside these two.
    cert_result = await certificate.run(ctx)
    readiness_result = await readiness.run(ctx, cert_result)
    return cert_result, readiness_result


async def _run_all_modules(ctx: ScanContext) -> Modules:
    (
        (cert_result, readiness_result),
        chain_result,
        tls_result,
        dns_result,
        email_result,
        headers_result,
    ) = await asyncio.gather(
        _run_certificate_then_readiness(ctx),
        chain.run(ctx),
        tls.run(ctx),
        dns_records.run(ctx),
        email_auth.run(ctx),
        headers.run(ctx),
    )
    return Modules(
        certificate=cert_result,
        chain=chain_result,
        tls=tls_result,
        dns=dns_result,
        email_auth=email_result,
        headers=headers_result,
        readiness=readiness_result,
    )


def _modules_as_pairs(
    modules: Modules,
) -> tuple[tuple[ModuleName, ModuleResult[Any] | None], ...]:
    return (
        (ModuleName.CERTIFICATE, modules.certificate),
        (ModuleName.CHAIN, modules.chain),
        (ModuleName.TLS, modules.tls),
        (ModuleName.DNS, modules.dns),
        (ModuleName.EMAIL_AUTH, modules.email_auth),
        (ModuleName.HEADERS, modules.headers),
        (ModuleName.READINESS, modules.readiness),
    )


async def _mark_failed(
    session: AsyncSession,
    record: ScanRecord,
    *,
    error_code: ErrorCode,
    message: str,
    started_at: datetime,
    completed_at: datetime,
) -> Scan:
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    scan = Scan(
        scan_id=str(record.scan_id),
        public_slug=record.public_slug,
        hostname=record.hostname,
        port=record.port,
        status=ScanStatus.FAILED,
        created_at=record.created_at,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        cached=False,
        overall_grade=None,
        overall_score=None,
        headline=None,
        share_url=share_url(record),
        counts=None,
        modules=EMPTY_MODULES,
        findings=[],
        error=ApiError(
            code=error_code,
            message=message,
            details=None,
            request_id=f"scan_{record.scan_id}",
        ),
    )
    record.status = ScanStatus.FAILED.value
    record.error_code = error_code.value
    record.error_message = message
    record.completed_at = completed_at
    record.duration_ms = duration_ms
    record.result = scan.model_dump(mode="json")
    await increment_daily_stat(session, "scans_failed", when=completed_at)
    await session.commit()
    return scan


async def _run_and_persist(
    session: AsyncSession, record: ScanRecord, *, scan_timeout_seconds: float
) -> Scan:
    started_at = datetime.now(UTC)
    record.status = ScanStatus.RUNNING.value
    record.started_at = started_at
    await session.commit()

    hostname = record.hostname
    port = record.port

    # Resolve-then-validate once, up front (contract §10 rules 1+2). A
    # hostname that simply doesn't resolve is not an HTTP error by this
    # point — the request already returned 202 — so it becomes a failed
    # Scan (§7.4) instead, and no module ever runs.
    try:
        await resolve_and_validate(hostname)
    except HostnameResolutionError:
        return await _mark_failed(
            session,
            record,
            error_code=ErrorCode.SCAN_FAILED,
            message=f"'{hostname}' does not resolve.",
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    except ApiException as exc:
        # BLOCKED_TARGET is normally a synchronous 400 at submission time;
        # reaching it here means the target changed (e.g. DNS rebinding)
        # between submission and execution. There is no live HTTP request
        # left to return 400 to, so this becomes SCAN_FAILED too.
        return await _mark_failed(
            session,
            record,
            error_code=ErrorCode.SCAN_FAILED,
            message=exc.message,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    now = started_at
    ctx = ScanContext(hostname=hostname, port=port, now=now)

    try:
        modules = await asyncio.wait_for(_run_all_modules(ctx), timeout=scan_timeout_seconds)
    except TimeoutError:
        return await _mark_failed(
            session,
            record,
            error_code=ErrorCode.UPSTREAM_TIMEOUT,
            message="The scan took too long to complete.",
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    module_inputs = [
        ModuleScoreInput(module=name, status=result.status, findings=result.findings)
        for name, result in _modules_as_pairs(modules)
        if result is not None
    ]
    grading_result = grade_scan(module_inputs)

    completed_at = datetime.now(UTC)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)

    scan = Scan(
        scan_id=str(record.scan_id),
        public_slug=record.public_slug,
        hostname=hostname,
        port=port,
        status=ScanStatus.COMPLETED,
        created_at=record.created_at,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        cached=False,
        overall_grade=grading_result.overall_grade,
        overall_score=grading_result.overall_score,
        headline=grading_result.headline,
        share_url=share_url(record),
        counts=SeverityCounts(
            critical=grading_result.counts[Severity.CRITICAL],
            high=grading_result.counts[Severity.HIGH],
            medium=grading_result.counts[Severity.MEDIUM],
            low=grading_result.counts[Severity.LOW],
            info=grading_result.counts[Severity.INFO],
        ),
        modules=modules,
        findings=grading_result.findings,
        error=None,
    )

    record.status = ScanStatus.COMPLETED.value
    record.overall_grade = grading_result.overall_grade.value
    record.overall_score = grading_result.overall_score
    record.headline = grading_result.headline
    record.result = scan.model_dump(mode="json")
    record.completed_at = completed_at
    record.duration_ms = duration_ms
    await increment_daily_stat(session, "scans_completed", when=completed_at)
    await session.commit()
    return scan


async def run_scan(
    session: AsyncSession, scan_id: str, *, scan_timeout_seconds: float | None = None
) -> Scan:
    """Loads the queued `scans` row for `scan_id`, runs the full scan against
    it, persists the result, and returns the assembled `Scan`."""
    settings = get_settings()
    if scan_timeout_seconds is not None:
        timeout = scan_timeout_seconds
    else:
        timeout = settings.scan_timeout_seconds

    record = await session.get(ScanRecord, uuid.UUID(scan_id))
    if record is None:
        raise ValueError(f"No scan record for scan_id={scan_id}")

    try:
        return await _run_and_persist(session, record, scan_timeout_seconds=timeout)
    except Exception:
        logger.exception("scan_orchestration_failed", extra={"scan_id": scan_id})
        started_at = record.started_at or datetime.now(UTC)
        return await _mark_failed(
            session,
            record,
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Something went wrong while scanning. Try again shortly.",
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
