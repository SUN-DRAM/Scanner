"""`GET .../scan-progress` (contract §7.16, v3.9/v3.10): domain-state
counts, in-flight, `started_at`, the `estimated_completion_at` honesty
rule (null below a 10-domain sample — human sign-off, same principle as
the partial-scan score ceiling), recent outcomes, and Step 6's metrics.

Reuses `test_outreach_scanner.py`'s fixtures/helpers rather than
duplicating campaign/prospect/domain/scan setup a second time.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ModuleErrorCode, OutreachCampaignStatus, ScanStatus
from app.models import OutreachCampaignRecord
from app.outreach.progress import MIN_SETTLED_FOR_ESTIMATE, build_scan_progress
from tests.test_outreach_scanner import (
    _add_domain,
    _add_prospect,
    _add_scan,
    _completed_result,
    _completed_result_with_module_error,
    _delete_campaign,
)


@pytest.fixture
async def campaign(db_session: AsyncSession) -> AsyncGenerator[OutreachCampaignRecord]:
    record = OutreachCampaignRecord(
        campaign_id=uuid.uuid4(),
        name="Progress test campaign",
        status=OutreachCampaignStatus.RUNNING.value,
    )
    db_session.add(record)
    await db_session.commit()
    try:
        yield record
    finally:
        await _delete_campaign(db_session, record.campaign_id)


async def test_domain_state_counts_all_keys_present_and_correct(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(db_session, prospect.prospect_id, state="pending")
    await _add_domain(db_session, prospect.prospect_id, state="pending")
    await _add_domain(db_session, prospect.prospect_id, state="running")
    await _add_domain(db_session, prospect.prospect_id, state="completed")

    progress = await build_scan_progress(db_session, campaign)
    assert progress.domain_state_counts["pending"] == 2
    assert progress.domain_state_counts["running"] == 1
    assert progress.domain_state_counts["completed"] == 1
    assert progress.domain_state_counts["completed_partial"] == 0
    assert progress.domain_state_counts["retrying"] == 0
    assert progress.domain_state_counts["failed"] == 0
    assert progress.in_flight == 1


async def test_started_at_null_when_nothing_touched(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(db_session, prospect.prospect_id, state="pending")

    progress = await build_scan_progress(db_session, campaign)
    assert progress.started_at is None
    assert progress.estimated_completion_at is None
    assert progress.metrics.total_wall_time_ms is None


async def test_estimated_completion_null_below_minimum_sample(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    """Human sign-off: two settled domains out of 150 is not a basis for a
    completion time — held null until MIN_SETTLED_FOR_ESTIMATE domains
    have actually settled, however long the batch has been running."""
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    started = datetime.now(UTC) - timedelta(minutes=10)
    assert MIN_SETTLED_FOR_ESTIMATE > 2
    for _ in range(2):
        await _add_domain(
            db_session, prospect.prospect_id, state="completed", updated_at=started
        )
    for _ in range(20):
        await _add_domain(db_session, prospect.prospect_id, state="pending")

    progress = await build_scan_progress(db_session, campaign)
    assert progress.estimated_completion_at is None


async def test_estimated_completion_present_once_minimum_sample_settled(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    started = datetime.now(UTC) - timedelta(minutes=10)
    for _ in range(MIN_SETTLED_FOR_ESTIMATE):
        await _add_domain(
            db_session, prospect.prospect_id, state="completed", updated_at=started
        )
    await _add_domain(db_session, prospect.prospect_id, state="pending")

    progress = await build_scan_progress(db_session, campaign)
    assert progress.estimated_completion_at is not None
    assert progress.estimated_completion_at > datetime.now(UTC)


async def test_estimated_completion_null_when_nothing_remains(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    started = datetime.now(UTC) - timedelta(minutes=10)
    for _ in range(MIN_SETTLED_FOR_ESTIMATE):
        await _add_domain(
            db_session, prospect.prospect_id, state="completed", updated_at=started
        )

    progress = await build_scan_progress(db_session, campaign)
    assert progress.estimated_completion_at is None  # nothing left to estimate toward


async def test_total_wall_time_uses_now_while_unsettled_domains_remain(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    started = datetime.now(UTC) - timedelta(minutes=5)
    await _add_domain(db_session, prospect.prospect_id, state="completed", updated_at=started)
    await _add_domain(db_session, prospect.prospect_id, state="pending")

    progress = await build_scan_progress(db_session, campaign)
    assert progress.metrics.total_wall_time_ms is not None
    assert progress.metrics.total_wall_time_ms >= 5 * 60 * 1000


async def test_total_wall_time_freezes_once_fully_settled(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    started = datetime.now(UTC) - timedelta(minutes=10)
    finished = datetime.now(UTC) - timedelta(minutes=5)
    await _add_domain(db_session, prospect.prospect_id, state="completed", updated_at=started)
    await _add_domain(db_session, prospect.prospect_id, state="failed", updated_at=finished)

    progress = await build_scan_progress(db_session, campaign)
    # frozen at (finished - started) ~= 5 minutes, not (now - started) ~= 10
    assert progress.metrics.total_wall_time_ms is not None
    five_minutes_ms = 5 * 60 * 1000
    assert abs(progress.metrics.total_wall_time_ms - five_minutes_ms) < 2000


async def test_recent_outcomes_only_terminal_states_newest_first_capped_at_20(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(25):
        await _add_domain(
            db_session,
            prospect.prospect_id,
            state="completed",
            updated_at=base + timedelta(seconds=i),
        )
    await _add_domain(db_session, prospect.prospect_id, state="pending")
    await _add_domain(db_session, prospect.prospect_id, state="running")

    progress = await build_scan_progress(db_session, campaign)
    assert len(progress.recent_outcomes) == 20
    # newest (highest offset i=24) first
    settled_ats = [o.settled_at for o in progress.recent_outcomes]
    assert settled_ats == sorted(settled_ats, reverse=True)
    assert all(o.state == "completed" for o in progress.recent_outcomes)
    assert progress.recent_outcomes[0].agency_name == prospect.agency_name


async def test_clean_rate_and_counts(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(db_session, prospect.prospect_id, state="completed")
    await _add_domain(db_session, prospect.prospect_id, state="completed")
    await _add_domain(db_session, prospect.prospect_id, state="completed_partial")
    await _add_domain(db_session, prospect.prospect_id, state="failed")

    progress = await build_scan_progress(db_session, campaign)
    assert progress.metrics.clean_rate == 0.5
    assert progress.metrics.completed_partial_count == 1
    assert progress.metrics.failed_count == 1


async def test_clean_rate_null_when_campaign_has_no_domains(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    progress = await build_scan_progress(db_session, campaign)
    assert progress.metrics.clean_rate is None


async def test_completed_partial_by_module_error_reads_real_scan_data(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    scan = await _add_scan(
        db_session,
        status=ScanStatus.COMPLETED.value,
        result=_completed_result_with_module_error(ModuleErrorCode.CONNECTION_REFUSED),
    )
    await _add_domain(
        db_session,
        prospect.prospect_id,
        state="completed_partial",
        scan_attempts=1,
        scan_id=scan.scan_id,
    )

    progress = await build_scan_progress(db_session, campaign)
    assert progress.metrics.completed_partial_by_module_error == {"CONNECTION_REFUSED": 1}


async def test_failed_by_reason_groups_exact_scan_error_string(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(
        db_session, prospect.prospect_id, state="failed", scan_attempts=3
    )
    domain2 = await _add_domain(
        db_session, prospect.prospect_id, state="failed", scan_attempts=3
    )
    domain2.scan_error = "same reason"
    await db_session.commit()

    progress = await build_scan_progress(db_session, campaign)
    assert sum(progress.metrics.failed_by_reason.values()) == 2


async def test_median_and_p95_scan_duration(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    durations = [1000, 2000, 3000, 4000, 5000]
    for duration_ms in durations:
        scan = await _add_scan(
            db_session, status=ScanStatus.COMPLETED.value, result=_completed_result()
        )
        scan.duration_ms = duration_ms
        await db_session.commit()
        await _add_domain(
            db_session,
            prospect.prospect_id,
            state="completed",
            scan_attempts=1,
            scan_id=scan.scan_id,
        )

    progress = await build_scan_progress(db_session, campaign)
    assert progress.metrics.median_scan_duration_ms == 3000
    assert progress.metrics.p95_scan_duration_ms is not None
    assert progress.metrics.p95_scan_duration_ms >= 4000


async def test_retried_and_rescued_count(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    # succeeded on the first try — not "rescued"
    await _add_domain(db_session, prospect.prospect_id, state="completed", scan_attempts=1)
    # took 2 attempts to succeed — rescued
    await _add_domain(db_session, prospect.prospect_id, state="completed", scan_attempts=2)
    # never succeeded despite retries — not rescued
    await _add_domain(db_session, prospect.prospect_id, state="failed", scan_attempts=3)

    progress = await build_scan_progress(db_session, campaign)
    assert progress.metrics.retried_and_rescued_count == 1


async def test_campaign_status_reflected_in_progress(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    campaign.status = OutreachCampaignStatus.PAUSED.value
    await db_session.commit()

    progress = await build_scan_progress(db_session, campaign)
    assert progress.campaign_status == "paused"
    assert progress.campaign_id == str(campaign.campaign_id)
