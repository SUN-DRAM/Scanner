"""`GET /api/v1/admin/accounts/{org_id}` (contract §7.13) — one organisation
in full: members, monitored hostnames, subscription and invoices, alert
delivery history (failures surfaced separately), and recent scans.

Serialisation reuses the existing per-router `_*_to_schema` helpers rather
than reimplementing them — the admin surface shows the same customer shapes
(`Organisation`, `Subscription`, `MonitoredHostname`, ...), so there must be
exactly one place each is built.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AlertState
from app.errors import ApiException, ErrorCode
from app.models import (
    AlertEventRecord,
    InvoiceRecord,
    MembershipRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    ScanRecord,
    SubscriptionRecord,
    UserRecord,
)
from app.routers.billing import _invoice_to_schema, _subscription_to_schema
from app.routers.monitors import _monitor_to_schema
from app.routers.orgs import _membership_to_schema, _org_to_schema
from app.scanner.orchestrator import share_url
from app.schemas import AdminAccountDetail, AdminAlertRow, AdminScanRow

_RECENT_ALERTS_LIMIT = 50
_FAILED_ALERTS_LIMIT = 50
_RECENT_SCANS_LIMIT = 50


def _not_found(org_id: str) -> ApiException:
    return ApiException(ErrorCode.NOT_FOUND, "No organisation found.", {"org_id": org_id})


def _admin_alert_row(
    record: AlertEventRecord, hostname_by_monitor: dict[uuid.UUID, str]
) -> AdminAlertRow:
    # Mirrors routers/monitors.py's _alert_event_to_schema (the AlertEvent
    # shape is contract-locked, §6.11) plus the resolved hostname.
    return AdminAlertRow(
        alert_id=str(record.alert_id),
        org_id=str(record.org_id),
        monitor_id=str(record.monitor_id),
        type=record.type,  # type: ignore[arg-type]
        state=record.state,  # type: ignore[arg-type]
        severity=record.severity,  # type: ignore[arg-type]
        subject=record.subject,
        dedupe_key=record.dedupe_key,
        scheduled_for=record.scheduled_for,
        sent_at=record.sent_at,
        recipients=record.recipients,
        payload=record.payload,
        monitor_hostname=hostname_by_monitor.get(record.monitor_id, "unknown"),
    )


def _admin_scan_row(record: ScanRecord) -> AdminScanRow:
    return AdminScanRow(
        scan_id=str(record.scan_id),
        public_slug=record.public_slug,
        hostname=record.hostname,
        status=record.status,  # type: ignore[arg-type]
        grade=record.overall_grade,  # type: ignore[arg-type]
        score=record.overall_score,
        created_at=record.created_at,
        share_url=share_url(record),
    )


async def build_account_detail(session: AsyncSession, org_id: str) -> AdminAccountDetail:
    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError as exc:
        raise _not_found(org_id) from exc

    org = await session.get(OrganisationRecord, org_uuid)
    if org is None:
        raise _not_found(org_id)

    member_rows = (
        await session.execute(
            select(MembershipRecord, UserRecord.email)
            .join(UserRecord, UserRecord.user_id == MembershipRecord.user_id)
            .where(MembershipRecord.org_id == org_uuid)
            .order_by(MembershipRecord.joined_at.asc())
        )
    ).all()
    members = [_membership_to_schema(membership, email) for membership, email in member_rows]

    subscription_record = (
        await session.execute(
            select(SubscriptionRecord).where(SubscriptionRecord.org_id == org_uuid)
        )
    ).scalar_one_or_none()
    subscription = (
        _subscription_to_schema(subscription_record) if subscription_record is not None else None
    )

    invoice_records = (
        (
            await session.execute(
                select(InvoiceRecord)
                .where(InvoiceRecord.org_id == org_uuid)
                .order_by(InvoiceRecord.issued_at.desc())
            )
        )
        .scalars()
        .all()
    )
    invoices = [_invoice_to_schema(record) for record in invoice_records]

    monitor_records = (
        (
            await session.execute(
                select(MonitoredHostnameRecord)
                .where(MonitoredHostnameRecord.org_id == org_uuid)
                .order_by(MonitoredHostnameRecord.cert_not_after.asc().nullslast())
            )
        )
        .scalars()
        .all()
    )
    monitors = [_monitor_to_schema(record) for record in monitor_records]
    hostname_by_monitor = {record.monitor_id: record.hostname for record in monitor_records}

    recent_alert_records = (
        (
            await session.execute(
                select(AlertEventRecord)
                .where(AlertEventRecord.org_id == org_uuid)
                .order_by(AlertEventRecord.scheduled_for.desc())
                .limit(_RECENT_ALERTS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    recent_alerts = [
        _admin_alert_row(record, hostname_by_monitor) for record in recent_alert_records
    ]

    failed_alert_records = (
        (
            await session.execute(
                select(AlertEventRecord)
                .where(
                    AlertEventRecord.org_id == org_uuid,
                    AlertEventRecord.state == AlertState.FAILED.value,
                )
                .order_by(AlertEventRecord.scheduled_for.desc())
                .limit(_FAILED_ALERTS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    failed_alerts = [
        _admin_alert_row(record, hostname_by_monitor) for record in failed_alert_records
    ]

    recent_scans: list[AdminScanRow] = []
    monitor_ids = list(hostname_by_monitor.keys())
    if monitor_ids:
        scan_records = (
            (
                await session.execute(
                    select(ScanRecord)
                    .where(ScanRecord.monitor_id.in_(monitor_ids))
                    .order_by(ScanRecord.created_at.desc())
                    .limit(_RECENT_SCANS_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        recent_scans = [_admin_scan_row(record) for record in scan_records]

    return AdminAccountDetail(
        org=_org_to_schema(org),
        members=members,
        subscription=subscription,
        invoices=invoices,
        monitors=monitors,
        failed_alerts=failed_alerts,
        recent_alerts=recent_alerts,
        recent_scans=recent_scans,
    )
