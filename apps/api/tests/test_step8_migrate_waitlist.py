"""`app/commands/migrate_waitlist.py` (Step 8): per waitlist signup, creates
a user, a personal org, a monitor, and a recipient, then sends one email —
idempotently, and without creating a second org for an email that already
has a real account.

`db_session` is a real, persistent Postgres database (see conftest.py)
shared across test runs, not a per-test transaction — other test files
(test_waitlist_router.py in particular) leave their own un-migrated
`waitlist_signups` rows behind, and `migrate_waitlist` processes every row
in the table, not just the ones a given test created. Every assertion below
keys off this test's own randomly generated email/hostname rather than
global counts (`processed`, `len(sender.sent)`), so it stays correct
regardless of what earlier test runs left lying around.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.migrate_waitlist import migrate_waitlist
from app.models import (
    AlertRecipientRecord,
    MembershipRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    ScanRecord,
    UserRecord,
    WaitlistSignupRecord,
)
from app.otp import create_personal_org, find_or_create_user


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})

    def sent_to(self, email: str) -> list[dict[str, str]]:
        return [message for message in self.sent if message["to"] == email]


async def _make_signup(session: AsyncSession, *, email: str, hostname: str) -> WaitlistSignupRecord:
    scan = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        status="completed",
    )
    session.add(scan)
    await session.flush()

    signup = WaitlistSignupRecord(
        id=uuid.uuid4(), email=email, hostname=hostname, scan_id=scan.scan_id
    )
    session.add(signup)
    await session.commit()
    return signup


async def test_migrates_a_signup_into_user_org_monitor_and_recipient(
    db_session: AsyncSession,
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    hostname = f"watch-me-{uuid.uuid4().hex}.example.com"
    await _make_signup(db_session, email=email, hostname=hostname)
    sender = FakeEmailSender()

    processed = await migrate_waitlist(db_session, sender)
    assert processed >= 1

    user = (
        await db_session.execute(select(UserRecord).where(UserRecord.email == email))
    ).scalar_one()

    membership = (
        await db_session.execute(
            select(MembershipRecord).where(MembershipRecord.user_id == user.user_id)
        )
    ).scalar_one()
    org = await db_session.get(OrganisationRecord, membership.org_id)
    assert org is not None
    assert org.plan_code == "free"

    monitor = (
        await db_session.execute(
            select(MonitoredHostnameRecord).where(
                MonitoredHostnameRecord.org_id == org.org_id,
                MonitoredHostnameRecord.hostname == hostname,
            )
        )
    ).scalar_one()

    recipient = (
        await db_session.execute(
            select(AlertRecipientRecord).where(
                AlertRecipientRecord.monitor_id == monitor.monitor_id
            )
        )
    ).scalar_one()
    assert recipient.email == email
    assert recipient.verified is True

    messages = sender.sent_to(email)
    assert len(messages) == 1
    assert hostname in messages[0]["subject"]
    assert hostname in messages[0]["text"]
    assert "/app" in messages[0]["text"]


async def test_rerunning_is_idempotent_and_does_not_resend_email(
    db_session: AsyncSession,
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    hostname = f"idempotent-{uuid.uuid4().hex}.example.com"
    await _make_signup(db_session, email=email, hostname=hostname)
    sender = FakeEmailSender()

    await migrate_waitlist(db_session, sender)
    await migrate_waitlist(db_session, sender)

    users = (
        await db_session.execute(select(UserRecord).where(UserRecord.email == email))
    ).scalars().all()
    assert len(users) == 1

    monitors = (
        await db_session.execute(
            select(MonitoredHostnameRecord).where(MonitoredHostnameRecord.hostname == hostname)
        )
    ).scalars().all()
    assert len(monitors) == 1

    # The whole point of the DUPLICATE_HOSTNAME short-circuit: a second run
    # must not re-notify someone who was already told once.
    assert len(sender.sent_to(email)) == 1


async def test_an_already_registered_email_reuses_its_existing_org(
    db_session: AsyncSession,
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    existing_user, _ = await find_or_create_user(db_session, email)
    existing_org = await create_personal_org(db_session, existing_user)
    await db_session.commit()

    hostname = f"already-a-user-{uuid.uuid4().hex}.example.com"
    await _make_signup(db_session, email=email, hostname=hostname)
    sender = FakeEmailSender()

    await migrate_waitlist(db_session, sender)

    orgs = (
        await db_session.execute(
            select(MembershipRecord).where(MembershipRecord.user_id == existing_user.user_id)
        )
    ).scalars().all()
    # Still exactly one membership/org for this user — no second personal
    # org was created for an email that already had a real account.
    assert len(orgs) == 1

    monitor = (
        await db_session.execute(
            select(MonitoredHostnameRecord).where(MonitoredHostnameRecord.hostname == hostname)
        )
    ).scalar_one()
    assert monitor.org_id == existing_org.org_id
    assert len(sender.sent_to(email)) == 1
