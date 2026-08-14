"""Tests for email OTP request/verify (contract §7.6)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OtpPurpose, UserRole
from app.errors import ApiException, ErrorCode
from app.models import MembershipRecord, OrganisationRecord, OtpCodeRecord, UserRecord
from app.otp import MAX_VERIFY_ATTEMPTS, request_otp, verify_otp

_CODE_PATTERN = re.compile(r"\b(\d{6})\b")


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


def _extract_code(sender: FakeEmailSender) -> str:
    match = _CODE_PATTERN.search(sender.sent[-1]["text"])
    assert match is not None
    return match.group(1)


def _random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


@pytest.mark.asyncio
async def test_request_otp_sends_regardless_of_whether_the_user_exists(
    db_session: AsyncSession,
) -> None:
    existing_email = _random_email()
    db_session.add(UserRecord(user_id=uuid.uuid4(), email=existing_email))
    await db_session.commit()

    new_email = _random_email()
    sender = FakeEmailSender()

    await request_otp(db_session, sender, email=existing_email)
    await request_otp(db_session, sender, email=new_email)

    sent_to = [message["to"] for message in sender.sent]
    assert existing_email in sent_to
    assert new_email in sent_to


@pytest.mark.asyncio
async def test_verify_otp_with_correct_code_creates_user_and_personal_org(
    db_session: AsyncSession,
) -> None:
    email = _random_email()
    sender = FakeEmailSender()
    await request_otp(db_session, sender, email=email)
    code = _extract_code(sender)

    user = await verify_otp(db_session, email=email, code=code)

    assert user.email == email
    assert user.email_verified is True
    assert user.last_login_at is not None

    memberships = (
        (
            await db_session.execute(
                select(MembershipRecord).where(MembershipRecord.user_id == user.user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(memberships) == 1
    assert memberships[0].role == UserRole.OWNER.value

    org = await db_session.get(OrganisationRecord, memberships[0].org_id)
    assert org is not None


@pytest.mark.asyncio
async def test_verify_otp_reuses_pre_created_invited_user_without_a_second_org(
    db_session: AsyncSession,
) -> None:
    # Simulates the invite flow (routers/orgs.py invite_member): the user
    # row and a membership exist before this person ever logs in.
    email = _random_email()
    invited_user = UserRecord(user_id=uuid.uuid4(), email=email, email_verified=False)
    db_session.add(invited_user)
    await db_session.flush()
    org = OrganisationRecord(
        org_id=uuid.uuid4(), name="Acme", country="IN", currency="INR", plan_code="watch"
    )
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        MembershipRecord(
            org_id=org.org_id, user_id=invited_user.user_id, role=UserRole.MEMBER.value
        )
    )
    await db_session.commit()

    sender = FakeEmailSender()
    await request_otp(db_session, sender, email=email)
    code = _extract_code(sender)

    user = await verify_otp(db_session, email=email, code=code)

    assert user.user_id == invited_user.user_id
    memberships = (
        (
            await db_session.execute(
                select(MembershipRecord).where(MembershipRecord.user_id == user.user_id)
            )
        )
        .scalars()
        .all()
    )
    # Still exactly the one membership from the invite — no personal org
    # created on top of it.
    assert len(memberships) == 1
    assert memberships[0].org_id == org.org_id


@pytest.mark.asyncio
async def test_verify_otp_rejects_wrong_code(db_session: AsyncSession) -> None:
    email = _random_email()
    sender = FakeEmailSender()
    await request_otp(db_session, sender, email=email)

    with pytest.raises(ApiException) as exc_info:
        await verify_otp(db_session, email=email, code="000000")
    assert exc_info.value.code == ErrorCode.OTP_INVALID


@pytest.mark.asyncio
async def test_verify_otp_rejects_expired_code(db_session: AsyncSession) -> None:
    email = _random_email()
    sender = FakeEmailSender()
    await request_otp(db_session, sender, email=email)
    code = _extract_code(sender)

    stmt = select(OtpCodeRecord).where(
        OtpCodeRecord.email == email, OtpCodeRecord.purpose == OtpPurpose.LOGIN.value
    )
    record = (await db_session.execute(stmt)).scalar_one()
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    with pytest.raises(ApiException) as exc_info:
        await verify_otp(db_session, email=email, code=code)
    assert exc_info.value.code == ErrorCode.OTP_EXPIRED


@pytest.mark.asyncio
async def test_verify_otp_burns_code_after_max_attempts(db_session: AsyncSession) -> None:
    email = _random_email()
    sender = FakeEmailSender()
    await request_otp(db_session, sender, email=email)
    code = _extract_code(sender)

    for _ in range(MAX_VERIFY_ATTEMPTS):
        with pytest.raises(ApiException) as exc_info:
            await verify_otp(db_session, email=email, code="000000")
        assert exc_info.value.code == ErrorCode.OTP_INVALID

    # The correct code, on the attempt after the limit, is still rejected —
    # the code is burned regardless of whether this guess would have worked.
    with pytest.raises(ApiException) as exc_info:
        await verify_otp(db_session, email=email, code=code)
    assert exc_info.value.code == ErrorCode.OTP_INVALID


@pytest.mark.asyncio
async def test_verify_otp_is_single_use(db_session: AsyncSession) -> None:
    email = _random_email()
    sender = FakeEmailSender()
    await request_otp(db_session, sender, email=email)
    code = _extract_code(sender)

    await verify_otp(db_session, email=email, code=code)

    with pytest.raises(ApiException) as exc_info:
        await verify_otp(db_session, email=email, code=code)
    assert exc_info.value.code == ErrorCode.OTP_INVALID


@pytest.mark.asyncio
async def test_verify_otp_with_no_code_ever_requested(db_session: AsyncSession) -> None:
    with pytest.raises(ApiException) as exc_info:
        await verify_otp(db_session, email=_random_email(), code="123456")
    assert exc_info.value.code == ErrorCode.OTP_INVALID
