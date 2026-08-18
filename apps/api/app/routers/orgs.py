"""GET/PATCH /api/v1/orgs/current, GET/POST/DELETE /api/v1/orgs/current/members
(contract §Step 2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentOrgContext, get_current_org_context, require_roles
from app.enums import UserRole
from app.errors import ApiException, ErrorCode
from app.models import MembershipRecord, OrganisationRecord, UserRecord
from app.otp import normalize_email
from app.schemas import (
    MemberInviteRequest,
    MembershipWithEmail,
    Organisation,
    OrgUpdateRequest,
    PaginatedList,
)

router = APIRouter(prefix="/orgs", tags=["orgs"])

_MAX_PER_PAGE = 100  # contract §6.14
_MANAGE_MEMBERS_ROLES = (UserRole.OWNER, UserRole.ADMIN)
# Module-level singleton, not `Depends(require_roles(*_MANAGE_MEMBERS_ROLES))`
# inline at each call site: ruff B008 flags a function call in an argument
# default, and require_roles(...) is one even though the Depends(...) around
# it is exempted (see ruff.toml's extend-immutable-calls).
_require_manage_members = require_roles(*_MANAGE_MEMBERS_ROLES)


def _org_to_schema(org: OrganisationRecord) -> Organisation:
    return Organisation(
        org_id=str(org.org_id),
        name=org.name,
        country=org.country,
        currency=org.currency,  # type: ignore[arg-type]
        plan_code=org.plan_code,  # type: ignore[arg-type]
        timezone=org.timezone,
        quiet_hours_start=org.quiet_hours_start,
        quiet_hours_end=org.quiet_hours_end,
        digest_mode=org.digest_mode,  # type: ignore[arg-type]
        digest_hour=org.digest_hour,
        created_at=org.created_at,
    )


def _membership_to_schema(membership: MembershipRecord, email: str) -> MembershipWithEmail:
    return MembershipWithEmail(
        org_id=str(membership.org_id),
        user_id=str(membership.user_id),
        role=membership.role,  # type: ignore[arg-type]
        invited_by=str(membership.invited_by) if membership.invited_by else None,
        joined_at=membership.joined_at,
        email=email,
    )


@router.get("/current", response_model=Organisation)
async def get_current_organisation(
    context: CurrentOrgContext = Depends(get_current_org_context),
) -> Organisation:
    return _org_to_schema(context.org)


@router.patch("/current", response_model=Organisation)
async def update_current_organisation(
    payload: OrgUpdateRequest,
    context: CurrentOrgContext = Depends(_require_manage_members),
    session: AsyncSession = Depends(get_session),
) -> Organisation:
    # Every field optional; only the keys actually present in the request
    # are applied (§7.7/§7.12, same model_fields_set convention as
    # MonitorUpdateRequest, routers/monitors.py). `country`/`currency` drive
    # billing provider selection and are "changeable only before the first
    # subscription" (§Step 6) — deliberately not on this model at all, so
    # there's nothing here that could apply them even by accident.
    fields_set = payload.model_fields_set
    if "name" in fields_set and payload.name is not None:
        context.org.name = payload.name
    if "timezone" in fields_set and payload.timezone is not None:
        context.org.timezone = payload.timezone
    if "quiet_hours_start" in fields_set and payload.quiet_hours_start is not None:
        context.org.quiet_hours_start = payload.quiet_hours_start
    if "quiet_hours_end" in fields_set and payload.quiet_hours_end is not None:
        context.org.quiet_hours_end = payload.quiet_hours_end
    if "digest_mode" in fields_set and payload.digest_mode is not None:
        context.org.digest_mode = payload.digest_mode.value
    if "digest_hour" in fields_set and payload.digest_hour is not None:
        context.org.digest_hour = payload.digest_hour

    await session.commit()
    await session.refresh(context.org)
    return _org_to_schema(context.org)


@router.get("/current/members", response_model=PaginatedList[MembershipWithEmail])
async def list_members(
    context: CurrentOrgContext = Depends(get_current_org_context),
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=_MAX_PER_PAGE),
) -> PaginatedList[MembershipWithEmail]:
    base_stmt = (
        select(MembershipRecord, UserRecord.email)
        .join(UserRecord, UserRecord.user_id == MembershipRecord.user_id)
        .where(MembershipRecord.org_id == context.org.org_id)
    )
    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    stmt = (
        base_stmt.order_by(MembershipRecord.joined_at.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await session.execute(stmt)).all()
    items = [_membership_to_schema(membership, email) for membership, email in rows]

    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )


@router.post(
    "/current/members", response_model=MembershipWithEmail, status_code=status.HTTP_201_CREATED
)
async def invite_member(
    payload: MemberInviteRequest,
    response: Response,
    context: CurrentOrgContext = Depends(_require_manage_members),
    session: AsyncSession = Depends(get_session),
) -> MembershipWithEmail:
    email = normalize_email(payload.email)

    stmt = select(UserRecord).where(UserRecord.email == email)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        # "Member invites are an email plus a role. The invited person
        # completes the normal OTP login and is attached to the org. No
        # separate invite-token flow" (§Step 2) — the user row has to exist
        # now so the membership FK is satisfiable; app/otp.py's
        # verify_otp recognises this pre-created row on their first login
        # and skips creating a second, unwanted personal org for them.
        user = UserRecord(user_id=uuid.uuid4(), email=email, email_verified=False)
        session.add(user)
        await session.flush()

    existing = await session.get(
        MembershipRecord, {"org_id": context.org.org_id, "user_id": user.user_id}
    )
    if existing is not None:
        # Idempotent rather than a conflict error: re-inviting someone
        # already in the org updates their role instead of requiring a
        # separate "change role" endpoint that isn't otherwise in scope.
        existing.role = payload.role.value
        await session.commit()
        response.status_code = status.HTTP_200_OK
        return _membership_to_schema(existing, user.email)

    membership = MembershipRecord(
        org_id=context.org.org_id,
        user_id=user.user_id,
        role=payload.role.value,
        invited_by=context.membership.user_id,
    )
    session.add(membership)
    await session.commit()
    await session.refresh(membership)
    return _membership_to_schema(membership, user.email)


@router.delete(
    "/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def remove_member(
    user_id: str,
    context: CurrentOrgContext = Depends(_require_manage_members),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        parsed_user_id = uuid.UUID(user_id)
    except ValueError as exc:
        raise ApiException(
            ErrorCode.NOT_FOUND, "No member found.", {"user_id": user_id}
        ) from exc

    membership = await session.get(
        MembershipRecord, {"org_id": context.org.org_id, "user_id": parsed_user_id}
    )
    if membership is None:
        # Cross-org id (§7.6): a user_id belonging to a membership in a
        # DIFFERENT org must look identical to one that doesn't exist —
        # 404, never 403, so nothing here confirms that id's existence.
        raise ApiException(ErrorCode.NOT_FOUND, "No member found.", {"user_id": user_id})

    if UserRole(membership.role) == UserRole.OWNER:
        owner_count_stmt = (
            select(func.count())
            .select_from(MembershipRecord)
            .where(
                MembershipRecord.org_id == context.org.org_id,
                MembershipRecord.role == UserRole.OWNER.value,
            )
        )
        owner_count = (await session.execute(owner_count_stmt)).scalar_one()
        if owner_count <= 1:
            raise ApiException(
                ErrorCode.FORBIDDEN, "An organisation must keep at least one owner."
            )

    await session.delete(membership)
    await session.commit()
