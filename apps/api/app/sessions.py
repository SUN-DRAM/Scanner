"""The `sd_session` cookie: creation, resolution, sliding renewal, and
revocation (contract §7.6).

Cookie value: `{session_id}.{hmac_sha256(session_id, SESSION_SECRET)}`. The
signature is checked before the database is ever queried, so a forged or
tampered session_id is rejected for the cost of one HMAC comparison — the
`sessions` row itself holds no secret, only bookkeeping (`user_id`,
`expires_at`), so a leaked row is not a usable credential on its own.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import SessionRecord

SESSION_COOKIE_NAME = "sd_session"
SESSION_LIFETIME_DAYS = 30


class SessionSecretNotConfigured(Exception):
    """SESSION_SECRET is empty. Raised rather than silently signing with an
    empty key, which would make every session forgeable by anyone."""


def _require_secret(settings: Settings) -> str:
    if not settings.session_secret:
        raise SessionSecretNotConfigured(
            "SESSION_SECRET must be set to create or verify sessions."
        )
    return settings.session_secret


def _sign(session_id: uuid.UUID, secret: str) -> str:
    return hmac.new(secret.encode(), str(session_id).encode(), hashlib.sha256).hexdigest()


def _cookie_value(session_id: uuid.UUID, secret: str) -> str:
    return f"{session_id}.{_sign(session_id, secret)}"


def _parse_cookie_value(raw: str) -> tuple[uuid.UUID, str] | None:
    session_id_part, _, signature = raw.partition(".")
    if not signature:
        return None
    try:
        return uuid.UUID(session_id_part), signature
    except ValueError:
        return None


async def create_session(
    db_session: AsyncSession, settings: Settings, *, user_id: uuid.UUID
) -> str:
    """Persists a new session row and returns the signed cookie value."""
    secret = _require_secret(settings)
    now = datetime.now(UTC)
    record = SessionRecord(
        session_id=uuid.uuid4(),
        user_id=user_id,
        expires_at=now + timedelta(days=SESSION_LIFETIME_DAYS),
    )
    db_session.add(record)
    await db_session.commit()
    return _cookie_value(record.session_id, secret)


async def resolve_session(
    db_session: AsyncSession, settings: Settings, *, cookie_value: str
) -> SessionRecord | None:
    """Verifies the signature, then looks up and slides the session. Returns
    `None` on any failure (missing/tampered/unknown/expired) — callers turn
    that into `UNAUTHENTICATED`, never a more specific reason, so a forged
    cookie and an expired one are indistinguishable to the caller."""
    secret = _require_secret(settings)
    parsed = _parse_cookie_value(cookie_value)
    if parsed is None:
        return None
    session_id, signature = parsed
    if not hmac.compare_digest(_sign(session_id, secret), signature):
        return None

    record = await db_session.get(SessionRecord, session_id)
    if record is None:
        return None

    now = datetime.now(UTC)
    if record.expires_at.replace(tzinfo=UTC) < now:
        return None

    # Sliding renewal (§7.6): every successful resolution extends the
    # session rather than counting down from a fixed login time.
    record.expires_at = now + timedelta(days=SESSION_LIFETIME_DAYS)
    await db_session.commit()
    return record


async def revoke_session(db_session: AsyncSession, *, session_id: uuid.UUID) -> None:
    record = await db_session.get(SessionRecord, session_id)
    if record is not None:
        await db_session.delete(record)
        await db_session.commit()


def set_session_cookie(response: Response, settings: Settings, *, cookie_value: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=SESSION_LIFETIME_DAYS * 24 * 60 * 60,
        httponly=True,
        # Browsers refuse a Secure cookie over plain http:// — dev runs the
        # stack unencrypted on localhost, production is HTTPS-only (Caddy).
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
