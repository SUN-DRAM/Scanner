"""Tests for the sd_session cookie (contract §7.6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import SessionRecord, UserRecord
from app.sessions import (
    SessionSecretNotConfigured,
    _sign,
    create_session,
    resolve_session,
    revoke_session,
)


def _settings(session_secret: str = "test-secret") -> Settings:
    return Settings(SESSION_SECRET=session_secret)


async def _make_user(db_session: AsyncSession) -> UserRecord:
    user = UserRecord(user_id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_create_and_resolve_session_round_trips(db_session: AsyncSession) -> None:
    settings = _settings()
    user = await _make_user(db_session)

    cookie_value = await create_session(db_session, settings, user_id=user.user_id)
    record = await resolve_session(db_session, settings, cookie_value=cookie_value)

    assert record is not None
    assert record.user_id == user.user_id


@pytest.mark.asyncio
async def test_resolve_session_rejects_tampered_signature(db_session: AsyncSession) -> None:
    settings = _settings()
    user = await _make_user(db_session)
    cookie_value = await create_session(db_session, settings, user_id=user.user_id)

    session_id_part = cookie_value.partition(".")[0]
    tampered = f"{session_id_part}.0000000000000000000000000000000000000000000000000000000000000000"

    record = await resolve_session(db_session, settings, cookie_value=tampered)
    assert record is None


@pytest.mark.asyncio
async def test_resolve_session_rejects_wrong_secret(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    cookie_value = await create_session(db_session, _settings("secret-a"), user_id=user.user_id)

    record = await resolve_session(db_session, _settings("secret-b"), cookie_value=cookie_value)
    assert record is None


@pytest.mark.asyncio
async def test_resolve_session_rejects_unknown_session_id(db_session: AsyncSession) -> None:
    settings = _settings()
    # A well-signed cookie for a session_id that was never persisted.
    fake_id = uuid.uuid4()
    cookie_value = f"{fake_id}.{_sign(fake_id, settings.session_secret)}"

    record = await resolve_session(db_session, settings, cookie_value=cookie_value)
    assert record is None


@pytest.mark.asyncio
async def test_resolve_session_rejects_expired_session(db_session: AsyncSession) -> None:
    settings = _settings()
    user = await _make_user(db_session)
    cookie_value = await create_session(db_session, settings, user_id=user.user_id)
    session_id = uuid.UUID(cookie_value.partition(".")[0])

    record = await db_session.get(SessionRecord, session_id)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    resolved = await resolve_session(db_session, settings, cookie_value=cookie_value)
    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_session_slides_expiry_forward(db_session: AsyncSession) -> None:
    settings = _settings()
    user = await _make_user(db_session)
    cookie_value = await create_session(db_session, settings, user_id=user.user_id)
    session_id = uuid.UUID(cookie_value.partition(".")[0])

    record = await db_session.get(SessionRecord, session_id)
    assert record is not None
    record.expires_at = datetime.now(UTC) + timedelta(days=1)
    await db_session.commit()

    await resolve_session(db_session, settings, cookie_value=cookie_value)

    await db_session.refresh(record)
    assert record.expires_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(days=29)


@pytest.mark.asyncio
async def test_revoke_session_invalidates_it(db_session: AsyncSession) -> None:
    settings = _settings()
    user = await _make_user(db_session)
    cookie_value = await create_session(db_session, settings, user_id=user.user_id)
    session_id = uuid.UUID(cookie_value.partition(".")[0])

    await revoke_session(db_session, session_id=session_id)

    record = await resolve_session(db_session, settings, cookie_value=cookie_value)
    assert record is None


@pytest.mark.asyncio
async def test_create_session_refuses_empty_secret(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    with pytest.raises(SessionSecretNotConfigured):
        await create_session(db_session, _settings(""), user_id=user.user_id)
