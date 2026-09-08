"""`GET /api/v1/admin/accounts` (contract §7.13) — one row per organisation,
with the derived signals an operator works from during outreach.

Scale note: plan/date filters are pushed to SQL, but `health` is a derived
value (it depends on hostname count, last login, and the current time), so
health-filtering, sorting, and pagination happen in Python over the full
filtered set. At the org counts this product has during Phase 2.5 cold
outreach that is trivially fast and obviously correct; if the account base
grows past a few thousand this is the function to revisit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import RowMapping, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.health import compute_account_health
from app.admin.relative_time import format_relative
from app.enums import AccountHealth, AlertState, Grade, PlanCode, SubscriptionState, UserRole
from app.models import (
    AlertEventRecord,
    MembershipRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    SubscriptionRecord,
    UserRecord,
)
from app.monitors import compute_days_until_expiry
from app.plans import get_plan
from app.schemas import AdminAccountRow

# Best -> worst. `func.max(rank)` over a monitor group is therefore the
# worst grade across that org's hostnames.
_GRADE_ORDER: tuple[str, ...] = ("A+", "A", "B", "C", "D", "E", "F")

_PAYING_STATES: frozenset[str] = frozenset(
    {
        SubscriptionState.ACTIVE.value,
        SubscriptionState.TRIALING.value,
        SubscriptionState.PAST_DUE.value,
    }
)

# Sentinels that push a null value to the end regardless of sort direction.
_DT_MIN = datetime.min.replace(tzinfo=UTC)
_DT_MAX = datetime.max.replace(tzinfo=UTC)


def _start_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _grade_rank_expression() -> Any:
    """`CASE WHEN last_grade = 'A+' THEN 0 ... END` — a numeric rank, so
    `func.max(...)` yields the worst grade in a group (NULL for a monitor
    that has never been scanned, which max() then ignores)."""
    whens = [
        (MonitoredHostnameRecord.last_grade == grade, index)
        for index, grade in enumerate(_GRADE_ORDER)
    ]
    return case(*whens, else_=None)


def _build_row(row: RowMapping, now: datetime) -> AdminAccountRow:
    plan_code = PlanCode(row["plan_code"])
    last_login: datetime | None = row["last_login_at"]
    soonest_expiry: datetime | None = row["soonest_expiry_at"]
    worst_rank: int | None = row["worst_grade_rank"]
    hostname_count = int(row["hostname_count"])
    created_at: datetime = row["created_at"]

    return AdminAccountRow(
        org_id=str(row["org_id"]),
        name=row["name"],
        primary_email=row["primary_email"] or "unknown",
        plan_code=plan_code,
        created_at=created_at,
        signed_up_relative=format_relative(created_at, now),
        hostname_count=hostname_count,
        hostname_limit=get_plan(plan_code).hostname_limit,
        last_login_at=last_login,
        last_login_relative=(format_relative(last_login, now) if last_login is not None else None),
        last_scan_at=row["last_scan_at"],
        worst_grade=Grade(_GRADE_ORDER[worst_rank]) if worst_rank is not None else None,
        soonest_expiry_at=soonest_expiry,
        soonest_expiry_days=compute_days_until_expiry(soonest_expiry, now=now),
        alerts_sent_count=int(row["alerts_sent_count"]),
        health=compute_account_health(
            hostname_count=hostname_count, last_login_at=last_login, now=now
        ),
        is_paying=row["subscription_state"] in _PAYING_STATES,
    )


def _sorted(rows: list[AdminAccountRow], sort: str) -> list[AdminAccountRow]:
    if sort == "oldest":
        return sorted(rows, key=lambda r: _as_utc(r.created_at))
    if sort == "last_login":
        # Most recent first; "never" (null) sorts last.
        return sorted(
            rows,
            key=lambda r: _as_utc(r.last_login_at) if r.last_login_at else _DT_MIN,
            reverse=True,
        )
    if sort == "soonest_expiry":
        # Soonest first; "unknown" (null) sorts last.
        return sorted(
            rows,
            key=lambda r: _as_utc(r.soonest_expiry_at) if r.soonest_expiry_at else _DT_MAX,
        )
    # "newest" — the default
    return sorted(rows, key=lambda r: _as_utc(r.created_at), reverse=True)


async def list_account_rows(
    session: AsyncSession,
    *,
    plan: PlanCode | None,
    health: AccountHealth | None,
    signed_up_after: date | None,
    signed_up_before: date | None,
    sort: str,
    page: int,
    per_page: int,
) -> tuple[list[AdminAccountRow], int]:
    owner_email_sq = (
        select(
            MembershipRecord.org_id.label("org_id"),
            UserRecord.email.label("email"),
        )
        .join(UserRecord, UserRecord.user_id == MembershipRecord.user_id)
        .where(MembershipRecord.role == UserRole.OWNER.value)
        .order_by(MembershipRecord.org_id, MembershipRecord.joined_at.asc())
        .distinct(MembershipRecord.org_id)
        .subquery()
    )
    any_email_sq = (
        select(
            MembershipRecord.org_id.label("org_id"),
            UserRecord.email.label("email"),
        )
        .join(UserRecord, UserRecord.user_id == MembershipRecord.user_id)
        .order_by(MembershipRecord.org_id, MembershipRecord.joined_at.asc())
        .distinct(MembershipRecord.org_id)
        .subquery()
    )
    login_sq = (
        select(
            MembershipRecord.org_id.label("org_id"),
            func.max(UserRecord.last_login_at).label("last_login_at"),
        )
        .join(UserRecord, UserRecord.user_id == MembershipRecord.user_id)
        .group_by(MembershipRecord.org_id)
        .subquery()
    )
    hostname_sq = (
        select(
            MonitoredHostnameRecord.org_id.label("org_id"),
            func.count().label("hostname_count"),
            func.min(MonitoredHostnameRecord.cert_not_after).label("soonest_expiry_at"),
            func.max(MonitoredHostnameRecord.last_scanned_at).label("last_scan_at"),
            func.max(_grade_rank_expression()).label("worst_grade_rank"),
        )
        .group_by(MonitoredHostnameRecord.org_id)
        .subquery()
    )
    alerts_sq = (
        select(
            AlertEventRecord.org_id.label("org_id"),
            func.count().label("alerts_sent_count"),
        )
        .where(AlertEventRecord.state == AlertState.SENT.value)
        .group_by(AlertEventRecord.org_id)
        .subquery()
    )

    stmt = (
        select(
            OrganisationRecord.org_id.label("org_id"),
            OrganisationRecord.name.label("name"),
            OrganisationRecord.plan_code.label("plan_code"),
            OrganisationRecord.created_at.label("created_at"),
            func.coalesce(owner_email_sq.c.email, any_email_sq.c.email).label("primary_email"),
            login_sq.c.last_login_at.label("last_login_at"),
            func.coalesce(hostname_sq.c.hostname_count, 0).label("hostname_count"),
            hostname_sq.c.soonest_expiry_at.label("soonest_expiry_at"),
            hostname_sq.c.last_scan_at.label("last_scan_at"),
            hostname_sq.c.worst_grade_rank.label("worst_grade_rank"),
            func.coalesce(alerts_sq.c.alerts_sent_count, 0).label("alerts_sent_count"),
            SubscriptionRecord.state.label("subscription_state"),
        )
        .select_from(OrganisationRecord)
        .outerjoin(owner_email_sq, owner_email_sq.c.org_id == OrganisationRecord.org_id)
        .outerjoin(any_email_sq, any_email_sq.c.org_id == OrganisationRecord.org_id)
        .outerjoin(login_sq, login_sq.c.org_id == OrganisationRecord.org_id)
        .outerjoin(hostname_sq, hostname_sq.c.org_id == OrganisationRecord.org_id)
        .outerjoin(alerts_sq, alerts_sq.c.org_id == OrganisationRecord.org_id)
        .outerjoin(SubscriptionRecord, SubscriptionRecord.org_id == OrganisationRecord.org_id)
    )

    if plan is not None:
        stmt = stmt.where(OrganisationRecord.plan_code == plan.value)
    if signed_up_after is not None:
        stmt = stmt.where(OrganisationRecord.created_at >= _start_of_day_utc(signed_up_after))
    if signed_up_before is not None:
        stmt = stmt.where(
            OrganisationRecord.created_at < _start_of_day_utc(signed_up_before + timedelta(days=1))
        )

    now = datetime.now(UTC)
    result = await session.execute(stmt)
    rows = [_build_row(row, now) for row in result.mappings().all()]

    if health is not None:
        rows = [row for row in rows if row.health == health]

    rows = _sorted(rows, sort)
    total = len(rows)
    start = (page - 1) * per_page
    return rows[start : start + per_page], total
