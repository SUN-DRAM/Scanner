"""POST /api/v1/auth/otp/request, POST /api/v1/auth/otp/verify,
POST /api/v1/auth/logout, GET /api/v1/auth/me (contract §7.6/§7.7).
"""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.deps import get_current_user
from app.errors import ApiException, ErrorCode
from app.models import UserRecord
from app.notify.email import EmailSender, get_email_sender
from app.otp import request_otp, verify_otp
from app.ratelimit import RateLimitExceeded, enforce_otp_request_rate_limits
from app.redis_client import get_redis_client
from app.schemas import (
    LogoutResponse,
    OtpRequestRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    User,
)
from app.sessions import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    create_session,
    revoke_session,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_OTP_MESSAGE = "If that email has an account, we've sent a code."


def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


def _user_to_schema(user: UserRecord) -> User:
    return User(
        user_id=str(user.user_id),
        email=user.email,
        email_verified=user.email_verified,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post(
    "/otp/request", response_model=OtpRequestResponse, status_code=status.HTTP_202_ACCEPTED
)
async def request_otp_code(
    payload: OtpRequestRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis_client: Redis = Depends(get_redis_client),
    email_sender: EmailSender = Depends(get_email_sender),
) -> OtpRequestResponse:
    try:
        await enforce_otp_request_rate_limits(
            redis_client, client_ip=_client_ip(request), email=payload.email
        )
    except RateLimitExceeded as exc:
        minutes = max(1, exc.retry_after_seconds // 60)
        raise ApiException(
            ErrorCode.OTP_RATE_LIMITED,
            f"Too many code requests. Try again in {minutes} minutes.",
            {"retry_after_seconds": exc.retry_after_seconds},
        ) from exc

    await request_otp(session, email_sender, email=payload.email)
    # §7.6: identical response whether or not the account exists — reached
    # the same way either way, since request_otp never branches on that.
    return OtpRequestResponse(message=_GENERIC_OTP_MESSAGE)


@router.post("/otp/verify", response_model=User)
async def verify_otp_code(
    payload: OtpVerifyRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    user = await verify_otp(session, email=payload.email, code=payload.code)
    cookie_value = await create_session(session, settings, user_id=user.user_id)
    set_session_cookie(response, settings, cookie_value=cookie_value)
    return _user_to_schema(user)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> LogoutResponse:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_value:
        session_id_part = cookie_value.partition(".")[0]
        with contextlib.suppress(ValueError):
            await revoke_session(session, session_id=uuid.UUID(session_id_part))
    clear_session_cookie(response)
    return LogoutResponse(message="Logged out.")


@router.get("/me", response_model=User)
async def get_me(current_user: UserRecord = Depends(get_current_user)) -> User:
    return _user_to_schema(current_user)
