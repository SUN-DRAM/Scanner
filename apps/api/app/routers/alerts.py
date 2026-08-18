"""GET /api/v1/alerts/unsubscribe/{recipient_id} (contract §7.10) and
GET/POST /api/v1/alerts/recipients, DELETE /api/v1/alerts/recipients/{id}
(contract §7.12).

The unsubscribe route is deliberately a GET, not a POST, and deliberately
not behind get_current_user: this is the link an alert email's
"Unsubscribe" line points at, so it must work from a plain click with no
session and no JS. The recipient CRUD routes are the opposite — ordinary
authenticated, role-gated endpoints, same shape as routers/orgs.py's member
endpoints.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import unsubscribe_recipient
from app.db import get_session
from app.deps import CurrentOrgContext, get_current_org_context, require_roles
from app.enums import UserRole
from app.errors import ApiException, ErrorCode
from app.models import AlertRecipientRecord
from app.schemas import (
    AlertRecipient,
    AlertRecipientCreateRequest,
    PaginatedList,
    UnsubscribeResponse,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])

_MAX_PER_PAGE = 100  # contract §6.14
# Recipients are admin territory, not billing (§7.6: "admin — hostnames,
# alerts, members; no billing") — same role pair as routers/orgs.py's
# member management, a distinct instance for the same ruff B008 reason
# documented there.
_require_manage_alerts = require_roles(UserRole.OWNER, UserRole.ADMIN)


def _recipient_to_schema(record: AlertRecipientRecord) -> AlertRecipient:
    return AlertRecipient(
        recipient_id=str(record.recipient_id),
        org_id=str(record.org_id),
        monitor_id=str(record.monitor_id) if record.monitor_id else None,
        email=record.email,
        verified=record.verified,
        created_at=record.created_at,
    )


@router.get("/unsubscribe/{recipient_id}", response_model=UnsubscribeResponse)
async def unsubscribe(
    recipient_id: str, session: AsyncSession = Depends(get_session)
) -> UnsubscribeResponse:
    try:
        parsed_id = uuid.UUID(recipient_id)
    except ValueError as exc:
        raise ApiException(
            ErrorCode.NOT_FOUND, "No recipient found.", {"recipient_id": recipient_id}
        ) from exc

    recipient = await unsubscribe_recipient(session, parsed_id)
    if recipient is None:
        raise ApiException(
            ErrorCode.NOT_FOUND, "No recipient found.", {"recipient_id": recipient_id}
        )
    return UnsubscribeResponse(
        message="You will no longer receive alert emails at this address."
    )


@router.get("/recipients", response_model=PaginatedList[AlertRecipient])
async def list_recipients(
    context: CurrentOrgContext = Depends(get_current_org_context),
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_MAX_PER_PAGE),
) -> PaginatedList[AlertRecipient]:
    base_stmt = select(AlertRecipientRecord).where(
        AlertRecipientRecord.org_id == context.org.org_id
    )
    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    stmt = (
        base_stmt.order_by(AlertRecipientRecord.created_at.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [_recipient_to_schema(row) for row in rows]

    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )


@router.post(
    "/recipients", response_model=AlertRecipient, status_code=status.HTTP_201_CREATED
)
async def create_recipient(
    payload: AlertRecipientCreateRequest,
    response: Response,
    context: CurrentOrgContext = Depends(_require_manage_alerts),
    session: AsyncSession = Depends(get_session),
) -> AlertRecipient:
    monitor_uuid: uuid.UUID | None = None
    if payload.monitor_id is not None:
        try:
            monitor_uuid = uuid.UUID(payload.monitor_id)
        except ValueError as exc:
            raise ApiException(
                ErrorCode.NOT_FOUND, "No monitor found.", {"monitor_id": payload.monitor_id}
            ) from exc

    email = payload.email.strip().lower()
    existing_stmt = select(AlertRecipientRecord).where(
        AlertRecipientRecord.org_id == context.org.org_id,
        AlertRecipientRecord.monitor_id == monitor_uuid,
        AlertRecipientRecord.email == email,
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        # Idempotent, not a conflict (§7.12) — same convention as
        # POST /orgs/current/members re-inviting an existing member.
        response.status_code = status.HTTP_200_OK
        return _recipient_to_schema(existing)

    record = AlertRecipientRecord(
        recipient_id=uuid.uuid4(),
        org_id=context.org.org_id,
        monitor_id=monitor_uuid,
        email=email,
        # True at creation, not pending a verification flow — §7.12: no
        # such flow exists anywhere in Phase 2, and delivery (§7.10) never
        # gates on this flag, only on `unsubscribed`.
        verified=True,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return _recipient_to_schema(record)


@router.delete(
    "/recipients/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_recipient(
    recipient_id: str,
    context: CurrentOrgContext = Depends(_require_manage_alerts),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        parsed_id = uuid.UUID(recipient_id)
    except ValueError as exc:
        raise ApiException(
            ErrorCode.NOT_FOUND, "No recipient found.", {"recipient_id": recipient_id}
        ) from exc

    record = await session.get(AlertRecipientRecord, parsed_id)
    # Cross-org id (§7.6): 404, never 403.
    if record is None or record.org_id != context.org.org_id:
        raise ApiException(
            ErrorCode.NOT_FOUND, "No recipient found.", {"recipient_id": recipient_id}
        )

    await session.delete(record)
    await session.commit()
