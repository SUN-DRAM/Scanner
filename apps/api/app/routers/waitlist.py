"""`POST /api/v1/waitlist` (contract §7.5, Gate B item 1).

Captures an email against a scan so we can alert the visitor before that
certificate expires. Minimum viable: no confirmation email, no unsubscribe
flow, no dedup — those are Phase 2 once the alerting itself exists.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import ApiException, ErrorCode
from app.models import ScanRecord, WaitlistSignupRecord
from app.schemas import WaitlistCreateRequest, WaitlistCreateResponse
from app.stats import increment_daily_stat

router = APIRouter(tags=["waitlist"])


def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


@router.post("/waitlist", response_model=WaitlistCreateResponse)
async def create_waitlist_signup(
    payload: WaitlistCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WaitlistCreateResponse:
    not_found_message = f"No scan found for '{payload.scan_id}'."
    not_found_details = {"scan_id": payload.scan_id}
    try:
        scan_id = uuid.UUID(payload.scan_id)
    except ValueError as exc:
        raise ApiException(ErrorCode.SCAN_NOT_FOUND, not_found_message, not_found_details) from exc

    scan = await session.get(ScanRecord, scan_id)
    if scan is None:
        raise ApiException(ErrorCode.SCAN_NOT_FOUND, not_found_message, not_found_details)

    # Hostname comes from the scan record, not the request body — the one
    # the visitor scanned, never a client-supplied value that could drift
    # from it (CLAUDE.md rule 3: backend computes).
    ip_hash = hashlib.sha256(_client_ip(request).encode("utf-8")).hexdigest()
    signup = WaitlistSignupRecord(
        id=uuid.uuid4(),
        email=payload.email,
        hostname=scan.hostname,
        scan_id=scan.scan_id,
        client_ip_hash=ip_hash,
    )
    session.add(signup)
    await increment_daily_stat(session, "waitlist_signups")
    await session.commit()

    return WaitlistCreateResponse(
        hostname=scan.hostname,
        message=f"We'll email you 30 days before {scan.hostname} expires.",
    )
