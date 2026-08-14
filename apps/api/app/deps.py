"""FastAPI dependencies resolving `current_user` and `current_org` (contract
§7.6). Every authenticated endpoint depends on these — none reads an org_id
out of the request body to decide authorisation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.enums import UserRole
from app.errors import ApiException, ErrorCode
from app.models import MembershipRecord, OrganisationRecord, UserRecord
from app.sessions import SESSION_COOKIE_NAME, resolve_session, set_session_cookie


async def get_current_user(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserRecord:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        raise ApiException(ErrorCode.UNAUTHENTICATED, "Sign in to continue.")

    record = await resolve_session(session, settings, cookie_value=cookie_value)
    if record is None:
        raise ApiException(ErrorCode.UNAUTHENTICATED, "Your session has expired. Sign in again.")

    user = await session.get(UserRecord, record.user_id)
    if user is None:
        raise ApiException(ErrorCode.UNAUTHENTICATED, "Sign in to continue.")

    # Sliding renewal (§7.6) has to reach the browser too, not just the
    # `sessions` row `resolve_session` already extended — otherwise the
    # cookie's own Max-Age still counts down from login and the browser
    # drops it out from under an otherwise-still-valid server session. The
    # signed value itself doesn't change (session_id and its signature are
    # both unchanged) — only the Max-Age on this fresh Set-Cookie does.
    set_session_cookie(response, settings, cookie_value=cookie_value)
    return user


@dataclass(frozen=True)
class CurrentOrgContext:
    org: OrganisationRecord
    membership: MembershipRecord


async def get_current_org_context(
    current_user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CurrentOrgContext:
    # No org-switcher endpoint exists yet (out of Step 2's scope) — "current
    # org" is the membership the user joined first, i.e. their original or
    # personal org. A user invited into additional orgs later stays on this
    # one until a switcher is built.
    stmt = (
        select(MembershipRecord)
        .where(MembershipRecord.user_id == current_user.user_id)
        .order_by(MembershipRecord.joined_at.asc())
        .limit(1)
    )
    membership = (await session.execute(stmt)).scalar_one_or_none()
    if membership is None:
        # Unreachable in practice: every login path (app/otp.py) guarantees
        # at least a personal org. Not a client error, so not UNAUTHENTICATED.
        raise ApiException(ErrorCode.FORBIDDEN, "This account has no organisation.")

    org = await session.get(OrganisationRecord, membership.org_id)
    assert org is not None  # FK guarantees this; asserted, never guessed (CLAUDE.md rule 7)
    return CurrentOrgContext(org=org, membership=membership)


async def get_current_org(
    context: CurrentOrgContext = Depends(get_current_org_context),
) -> OrganisationRecord:
    return context.org


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[CurrentOrgContext]]:
    """Dependency factory: 403s unless the caller's role in the current org
    is one of `roles`. Enforced here, in one place, rather than re-checked
    in each handler (§7.6)."""

    async def _check(
        context: CurrentOrgContext = Depends(get_current_org_context),
    ) -> CurrentOrgContext:
        if UserRole(context.membership.role) not in roles:
            raise ApiException(
                ErrorCode.FORBIDDEN, "Your role doesn't allow this action."
            )
        return context

    return _check
