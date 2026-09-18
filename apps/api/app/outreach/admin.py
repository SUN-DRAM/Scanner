"""Stage 1 minimal admin surface (contract §7.15, docs/outreach_stage_1.md
Step 5). Just enough to verify the import worked — campaign create/list,
CSV upload, a bare prospect list. Not the Stage 5 review UI.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OutreachCampaignStatus, OutreachProspectState
from app.errors import ApiException, ErrorCode
from app.models import OutreachCampaignRecord, OutreachDomainRecord, OutreachProspectRecord
from app.outreach.importer import import_csv
from app.outreach.progress import build_scan_progress
from app.outreach.state_machine import transition_campaign
from app.schemas import (
    OutreachCampaign,
    OutreachCampaignRow,
    OutreachImportReport,
    OutreachImportWarning,
    OutreachProspectRow,
    OutreachRejectedRow,
    OutreachScanProgress,
    PaginatedList,
)


def _parse_campaign_id(campaign_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(campaign_id)
    except ValueError as exc:
        raise _not_found(campaign_id) from exc


def _not_found(campaign_id: str) -> ApiException:
    return ApiException(
        ErrorCode.NOT_FOUND, "No outreach campaign found.", {"campaign_id": campaign_id}
    )


async def _load_campaign(session: AsyncSession, campaign_id: str) -> OutreachCampaignRecord:
    parsed = _parse_campaign_id(campaign_id)
    campaign = await session.get(OutreachCampaignRecord, parsed)
    if campaign is None:
        raise _not_found(campaign_id)
    return campaign


async def _state_counts(
    session: AsyncSession, campaign_id: uuid.UUID
) -> dict[OutreachProspectState, int]:
    rows = (
        await session.execute(
            select(OutreachProspectRecord.state, func.count())
            .where(OutreachProspectRecord.campaign_id == campaign_id)
            .group_by(OutreachProspectRecord.state)
        )
    ).all()
    counts = dict.fromkeys(OutreachProspectState, 0)
    for state_value, count in rows:
        counts[OutreachProspectState(state_value)] = count
    return counts


async def _campaign_row(
    session: AsyncSession, campaign: OutreachCampaignRecord
) -> OutreachCampaignRow:
    counts = await _state_counts(session, campaign.campaign_id)
    return OutreachCampaignRow(
        campaign_id=str(campaign.campaign_id),
        name=campaign.name,
        status=OutreachCampaignStatus(campaign.status),
        created_at=campaign.created_at,
        prospect_count=sum(counts.values()),
        state_counts=counts,
    )


async def create_campaign(session: AsyncSession, *, name: str) -> OutreachCampaign:
    record = OutreachCampaignRecord(
        campaign_id=uuid.uuid4(), name=name, status=OutreachCampaignStatus.DRAFT.value
    )
    session.add(record)
    await session.commit()
    return OutreachCampaign(
        campaign_id=str(record.campaign_id),
        name=record.name,
        status=OutreachCampaignStatus(record.status),
        created_at=record.created_at,
    )


async def get_campaign(session: AsyncSession, campaign_id: str) -> OutreachCampaignRow:
    """Not one of docs/outreach_stage_1.md Step 5's four listed endpoints —
    added because the review page needs the campaign's own name/status,
    and the stage prompt names no way to fetch a single campaign. Same
    `GET .../{id}` precedent `AdminProspectBatchDetail` (§7.13) already
    set for the analogous prospect-batch feature."""
    campaign = await _load_campaign(session, campaign_id)
    return await _campaign_row(session, campaign)


async def list_campaigns(
    session: AsyncSession, *, page: int, per_page: int
) -> PaginatedList[OutreachCampaignRow]:
    total = (
        await session.execute(select(func.count()).select_from(OutreachCampaignRecord))
    ).scalar_one()
    campaigns = (
        (
            await session.execute(
                select(OutreachCampaignRecord)
                .order_by(OutreachCampaignRecord.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    items = [await _campaign_row(session, campaign) for campaign in campaigns]
    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )


def _invalid_status(
    campaign_id: uuid.UUID, status: OutreachCampaignStatus, action: str
) -> ApiException:
    return ApiException(
        ErrorCode.INVALID_CAMPAIGN_STATUS,
        f"Campaign is {status.value}; cannot {action}.",
        {"campaign_id": str(campaign_id), "campaign_status": status.value, "action": action},
    )


async def start_scan(
    session: AsyncSession, campaign_id: str, *, include_weak: bool
) -> OutreachCampaignRow:
    """§7.16. `.../scan` moves a `draft` campaign to `running` and is a
    no-op on an already-`running` one (still updates `include_weak`,
    letting an operator change it mid-batch) — refused on `paused`/
    `complete` (§7.16's own reasoning: a generic start button that also
    un-paused would make `paused` one click from meaningless). No worker
    job is enqueued here — `app/outreach/scanner.py`'s `outreach_scan_tick`
    runs on its own schedule and picks up any `running` campaign within
    `OUTREACH_SCAN_DELAY_SECONDS`, a correction from what this contract
    section originally speculated before Stage 2's tick architecture was
    decided."""
    campaign = await _load_campaign(session, campaign_id)
    status = OutreachCampaignStatus(campaign.status)
    if status not in (OutreachCampaignStatus.DRAFT, OutreachCampaignStatus.RUNNING):
        raise _invalid_status(campaign.campaign_id, status, "scan")

    campaign.include_weak_prospects = include_weak
    if status == OutreachCampaignStatus.DRAFT:
        transition_campaign(campaign, OutreachCampaignStatus.RUNNING, reason=None)
    await session.commit()
    return await _campaign_row(session, campaign)


async def pause_scan(session: AsyncSession, campaign_id: str) -> OutreachCampaignRow:
    """§7.16. `running -> paused` only — the tick's own claim step already
    checks campaign status before claiming, so this is a synchronous flag
    flip, nothing to enqueue or cancel."""
    campaign = await _load_campaign(session, campaign_id)
    status = OutreachCampaignStatus(campaign.status)
    if status != OutreachCampaignStatus.RUNNING:
        raise _invalid_status(campaign.campaign_id, status, "pause")

    transition_campaign(campaign, OutreachCampaignStatus.PAUSED, reason=None)
    await session.commit()
    return await _campaign_row(session, campaign)


async def resume_scan(session: AsyncSession, campaign_id: str) -> OutreachCampaignRow:
    """§7.16. `paused -> running` — the next tick (within
    `OUTREACH_SCAN_DELAY_SECONDS`) resumes claiming automatically; nothing
    to explicitly re-enqueue."""
    campaign = await _load_campaign(session, campaign_id)
    status = OutreachCampaignStatus(campaign.status)
    if status != OutreachCampaignStatus.PAUSED:
        raise _invalid_status(campaign.campaign_id, status, "resume")

    transition_campaign(campaign, OutreachCampaignStatus.RUNNING, reason=None)
    await session.commit()
    return await _campaign_row(session, campaign)


async def get_scan_progress(session: AsyncSession, campaign_id: str) -> OutreachScanProgress:
    campaign = await _load_campaign(session, campaign_id)
    return await build_scan_progress(session, campaign)


async def import_campaign_csv(
    session: AsyncSession, campaign_id: str, csv_bytes: bytes
) -> OutreachImportReport:
    # import_csv (Step 3) already 404s on an unknown campaign_id via its own
    # session.get lookup — parsed here first only so a malformed id (not a
    # valid UUID at all) gets the same 404 rather than a 500 from a failed
    # UUID cast inside that lookup.
    parsed = _parse_campaign_id(campaign_id)
    report = await import_csv(session, campaign_id=parsed, csv_bytes=csv_bytes)
    return OutreachImportReport(
        imported_agencies=report.imported_agencies,
        imported_domains=report.imported_domains,
        skipped_agencies=report.skipped_agencies,
        suppressed_agencies=report.suppressed_agencies,
        rejected_rows=[
            OutreachRejectedRow(row_number=row.row_number, reason=row.reason)
            for row in report.rejected_rows
        ],
        warnings=[
            OutreachImportWarning(contact_email=w.contact_email, message=w.message)
            for w in report.warnings
        ],
    )


async def list_prospects(
    session: AsyncSession,
    campaign_id: str,
    *,
    state: OutreachProspectState | None,
    page: int,
    per_page: int,
) -> PaginatedList[OutreachProspectRow]:
    campaign = await _load_campaign(session, campaign_id)

    conditions = [OutreachProspectRecord.campaign_id == campaign.campaign_id]
    if state is not None:
        conditions.append(OutreachProspectRecord.state == state.value)

    total = (
        await session.execute(
            select(func.count()).select_from(OutreachProspectRecord).where(*conditions)
        )
    ).scalar_one()
    prospects = (
        (
            await session.execute(
                select(OutreachProspectRecord)
                .where(*conditions)
                .order_by(OutreachProspectRecord.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )

    prospect_ids = [p.prospect_id for p in prospects]
    domain_counts: dict[uuid.UUID, int] = {}
    if prospect_ids:
        domain_count_rows = await session.execute(
            select(OutreachDomainRecord.prospect_id, func.count())
            .where(OutreachDomainRecord.prospect_id.in_(prospect_ids))
            .group_by(OutreachDomainRecord.prospect_id)
        )
        domain_counts = dict(domain_count_rows.tuples().all())

    items = [
        OutreachProspectRow(
            prospect_id=str(p.prospect_id),
            agency_name=p.agency_name,
            contact_name=p.contact_name,
            contact_email=p.contact_email,
            state=OutreachProspectState(p.state),
            state_reason=p.state_reason,
            domain_count=domain_counts.get(p.prospect_id, 0),
            created_at=p.created_at,
        )
        for p in prospects
    ]
    return PaginatedList(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=(page * per_page) < total,
    )
