"""Phase 2 Step 8: migrate Gate B's `waitlist_signups` into real accounts
(`docs/PHASE_2_PROMPT.md` Step 8).

Those rows predate every piece of Phase 2 — a stranger scanned a hostname
on the free public scanner and asked to be warned before its certificate
expired, before there was any account system to attach that promise to.
This command keeps it: per signup, it finds-or-creates the user (reusing
`app.otp`'s own user-creation path, the same one a real OTP login uses —
`users.email` is unique, so a signup email that already has a real account
must never go through a second, parallel creation path that would collide
with it), creates a personal free-plan org for a brand-new user (reusing
`app.otp.create_personal_org`) or reuses an already-registered user's
existing org (`app.otp.primary_org_for_user`), adds the hostname as a
monitor (`app.monitors.create_monitor` — §7.2/§10 normalisation and safety
guard, no parallel path), and adds the signup email as a recipient scoped
to that one monitor (`app.alerts.get_or_create_recipient` — the same
function `POST /alerts/recipients`, §7.12, uses). Then sends the one email
the phase prompt specifies.

Idempotent — safe to re-run. `create_monitor` raising `DUPLICATE_HOSTNAME`
means this signup already has a monitor for that hostname in the target
org, so the row is treated as already migrated: no email is sent again.
`QUOTA_EXCEEDED` (the target org already has 3/3 free-plan monitors from
something unrelated) and a rejected hostname (`INVALID_HOSTNAME` —
unreachable in practice, since Phase 1's own `POST /scans` already applies
the identical guard before a waitlist signup could ever have been created
against it) are logged and skipped rather than raised, so one bad row
never aborts the whole run.

Run once, from inside the api container:
    docker compose exec api python -m app.commands.migrate_waitlist
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import get_or_create_recipient
from app.config import get_settings
from app.db import get_sessionmaker
from app.errors import ApiException, ErrorCode
from app.logging_config import configure_logging
from app.models import OrganisationRecord, WaitlistSignupRecord
from app.monitors import count_quota_monitors, create_monitor
from app.notify.email import EmailSender, get_email_sender
from app.otp import create_personal_org, find_or_create_user, normalize_email, primary_org_for_user

logger = logging.getLogger("app.commands.migrate_waitlist")


async def _migrate_one(
    session: AsyncSession, email_sender: EmailSender, signup: WaitlistSignupRecord
) -> None:
    email = normalize_email(signup.email)
    user, is_new_user = await find_or_create_user(session, email)

    org: OrganisationRecord | None
    if is_new_user:
        org = await create_personal_org(session, user)
        await session.commit()
        await session.refresh(org)
    else:
        org = await primary_org_for_user(session, user.user_id)
        if org is None:
            # Unreachable via any login path (see app.otp.primary_org_for_
            # user's own docstring) but this reads rows that predate that
            # invariant existing at all — check, don't assume (CLAUDE.md
            # rule 7).
            logger.warning(
                "waitlist_migration_user_has_no_org",
                extra={"email": email, "signup_id": str(signup.id)},
            )
            return

    quota_count = await count_quota_monitors(session, org.org_id)
    try:
        monitor = await create_monitor(
            session,
            org,
            raw_hostname=signup.hostname,
            requested_port=None,
            label=None,
            notes="Migrated from the pre-signup waitlist.",
            current_quota_count=quota_count,
        )
    except ApiException as exc:
        if exc.code == ErrorCode.DUPLICATE_HOSTNAME:
            logger.info(
                "waitlist_migration_already_monitored",
                extra={"email": email, "hostname": signup.hostname},
            )
            return
        logger.warning(
            "waitlist_migration_monitor_failed",
            extra={"email": email, "hostname": signup.hostname, "code": exc.code.value},
        )
        return

    await get_or_create_recipient(
        session, org_id=org.org_id, monitor_id=monitor.monitor_id, email=email
    )

    await email_sender.send(
        to=email,
        subject=f"{signup.hostname} — we're now watching it",
        text=(
            f"You asked us to warn you before {signup.hostname}'s certificate expires. "
            "We're now watching it. Here's your dashboard:\n\n"
            f"{get_settings().public_base_url.rstrip('/')}/app\n\n"
            f"Sign in with {email} to see it."
        ),
    )
    logger.info(
        "waitlist_migration_signup_processed",
        extra={"email": email, "hostname": signup.hostname, "monitor_id": str(monitor.monitor_id)},
    )


async def migrate_waitlist(session: AsyncSession, email_sender: EmailSender) -> int:
    stmt = select(WaitlistSignupRecord).order_by(WaitlistSignupRecord.created_at.asc())
    signups = (await session.execute(stmt)).scalars().all()
    for signup in signups:
        await _migrate_one(session, email_sender, signup)
    return len(signups)


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings)
    email_sender = get_email_sender(settings)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        count = await migrate_waitlist(session, email_sender)
    logger.info("waitlist_migration_complete", extra={"signups_seen": count})


if __name__ == "__main__":
    asyncio.run(_main())
