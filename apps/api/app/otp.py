"""Email OTP: request, store, verify (contract §7.6). The one place a
`users`/`organisations`/`memberships` row is created from a login, mirroring
how `routers/scans.py` is the one place a `scans` row is created.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OtpPurpose, UserRole
from app.errors import ApiException, ErrorCode
from app.models import MembershipRecord, OrganisationRecord, OtpCodeRecord, UserRecord
from app.notify.email import EmailSender

OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
MAX_VERIFY_ATTEMPTS = 5


def normalize_email(raw_email: str) -> str:
    return raw_email.strip().lower()


def _generate_code() -> str:
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def _hash_code(email: str, code: str) -> str:
    # Salted with the email so the same 6-digit code for two different
    # addresses never produces the same stored hash.
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


async def request_otp(
    session: AsyncSession,
    email_sender: EmailSender,
    *,
    email: str,
    purpose: OtpPurpose = OtpPurpose.LOGIN,
) -> None:
    """Always generates and sends a code, regardless of whether `email`
    belongs to an existing user — §7.6 requires an identical response
    either way, which this satisfies trivially by never branching on
    existence in the first place."""
    normalized_email = normalize_email(email)
    code = _generate_code()
    now = datetime.now(UTC)

    record = OtpCodeRecord(
        id=uuid.uuid4(),
        email=normalized_email,
        purpose=purpose.value,
        code_hash=_hash_code(normalized_email, code),
        attempts=0,
        expires_at=now + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )
    session.add(record)
    await session.commit()

    await email_sender.send(
        to=normalized_email,
        subject="Your SUN-DRAM Scanner sign-in code",
        text=(
            f"Your code is {code}. It expires in {OTP_EXPIRY_MINUTES} minutes "
            "and can only be used once.\n\n"
            "If you didn't request this, you can ignore this email."
        ),
    )


async def _latest_active_code(
    session: AsyncSession, email: str, purpose: OtpPurpose
) -> OtpCodeRecord | None:
    stmt = (
        select(OtpCodeRecord)
        .where(
            OtpCodeRecord.email == email,
            OtpCodeRecord.purpose == purpose.value,
            OtpCodeRecord.consumed_at.is_(None),
        )
        .order_by(OtpCodeRecord.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _find_or_create_user(session: AsyncSession, email: str) -> tuple[UserRecord, bool]:
    stmt = select(UserRecord).where(UserRecord.email == email)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is not None:
        return user, False

    user = UserRecord(user_id=uuid.uuid4(), email=email, email_verified=False)
    session.add(user)
    await session.flush()
    return user, True


async def _create_personal_org(session: AsyncSession, user: UserRecord) -> None:
    org = OrganisationRecord(
        org_id=uuid.uuid4(),
        # Not specified by the phase prompt: personal orgs are named from the
        # account's own email local-part rather than left blank, so a brand
        # new user doesn't land on an empty-string org name in the dashboard.
        name=user.email.split("@", 1)[0],
        country="IN",
        currency="INR",
        plan_code="free",
    )
    session.add(org)
    await session.flush()
    session.add(
        MembershipRecord(
            org_id=org.org_id,
            user_id=user.user_id,
            role=UserRole.OWNER.value,
            invited_by=None,
        )
    )


async def verify_otp(
    session: AsyncSession,
    *,
    email: str,
    code: str,
    purpose: OtpPurpose = OtpPurpose.LOGIN,
) -> UserRecord:
    normalized_email = normalize_email(email)
    record = await _latest_active_code(session, normalized_email, purpose)

    if record is None:
        raise ApiException(ErrorCode.OTP_INVALID, "That code is not valid. Request a new one.")

    now = datetime.now(UTC)
    if record.expires_at.replace(tzinfo=UTC) < now:
        raise ApiException(ErrorCode.OTP_EXPIRED, "That code has expired. Request a new one.")

    if record.attempts >= MAX_VERIFY_ATTEMPTS:
        raise ApiException(
            ErrorCode.OTP_INVALID, "That code is no longer valid. Request a new one."
        )

    expected_hash = _hash_code(normalized_email, code)
    if not hmac.compare_digest(record.code_hash, expected_hash):
        record.attempts += 1
        await session.commit()
        raise ApiException(ErrorCode.OTP_INVALID, "That code is not valid. Try again.")

    record.consumed_at = now
    user, is_new_user = await _find_or_create_user(session, normalized_email)
    user.email_verified = True
    user.last_login_at = now

    # "Creates the user and a personal org on first login" (§Step 2): a
    # brand-new user row — one that didn't exist before this call, and so
    # cannot yet own any membership — gets a personal org. A user who
    # already existed — whether from a previous login or because someone
    # invited them to an org first (§Step 2 invite flow, no separate
    # invite-token path) — must not get a second, unwanted personal org.
    if is_new_user:
        await _create_personal_org(session, user)

    await session.commit()
    await session.refresh(user)
    return user
