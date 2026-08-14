"""GET /api/v1/alerts/unsubscribe/{recipient_id} (contract §7.10).

Deliberately a GET, not a POST, and deliberately not behind
get_current_user: this is the link an alert email's "Unsubscribe" line
points at, so it must work from a plain click with no session and no JS.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import unsubscribe_recipient
from app.db import get_session
from app.errors import ApiException, ErrorCode
from app.schemas import UnsubscribeResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


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
