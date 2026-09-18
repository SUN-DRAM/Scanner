"""Stage 2 batch scan runner (contract §7.16, spec §8): claim eligibility
(pending/retry-backoff/completed_partial-once/weak-prospect filtering),
outcome reconciliation (completed/completed_partial/failed/stale-crash),
retry-count semantics (3 total attempts before FAILED), and prospect
roll-up (ANALYZING needs a genuine COMPLETED, never just COMPLETED_PARTIAL).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import ModuleErrorCode, ModuleStatus, OutreachCampaignStatus, ScanStatus
from app.errors import ErrorCode
from app.models import (
    OutreachCampaignRecord,
    OutreachDomainRecord,
    OutreachProspectRecord,
    ScanRecord,
)
from app.outreach.scanner import (
    claim_and_start_domains,
    completed_domains_for_prospect,
    settle_running_domains,
)
from app.outreach.state_machine import CampaignPausedError
from app.scan_compat import stamp_schema_version
from tests.pdf_fixtures import default_modules, make_completed_scan


class _FakeArqPool:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue_job(self, function: str, *args: object, **_kwargs: object) -> None:
        self.enqueued.append((function, args))


class _FakeRedis:
    """A tiny in-memory stand-in for the sorted-set semaphore — real Redis
    behaviour (zadd/zcard/zremrangebyscore) is exercised separately by
    app/scheduler.py's own tests; this module only needs "always has
    capacity" to isolate claim logic from the semaphore."""

    def __init__(self) -> None:
        self._members: dict[str, float] = {}

    async def zremrangebyscore(self, _key: str, _min: float, _max: float) -> None:
        return None

    async def zcard(self, _key: str) -> int:
        return len(self._members)

    async def zadd(self, _key: str, mapping: dict[str, float]) -> None:
        self._members.update(mapping)

    async def zrem(self, _key: str, *members: str) -> None:
        for member in members:
            self._members.pop(member, None)


@pytest.fixture
def redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def arq_pool() -> _FakeArqPool:
    return _FakeArqPool()


async def _delete_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> None:
    await session.execute(
        delete(OutreachProspectRecord).where(OutreachProspectRecord.campaign_id == campaign_id)
    )
    await session.execute(
        delete(OutreachCampaignRecord).where(OutreachCampaignRecord.campaign_id == campaign_id)
    )
    await session.commit()


@pytest.fixture
async def campaign(db_session: AsyncSession) -> AsyncGenerator[OutreachCampaignRecord]:
    record = OutreachCampaignRecord(
        campaign_id=uuid.uuid4(),
        name="Scanner test campaign",
        status=OutreachCampaignStatus.RUNNING.value,
    )
    db_session.add(record)
    await db_session.commit()
    try:
        yield record
    finally:
        await _delete_campaign(db_session, record.campaign_id)


async def _add_prospect(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    *,
    icp_grade: str | None = None,
    state: str = "pending",
) -> OutreachProspectRecord:
    prospect = OutreachProspectRecord(
        prospect_id=uuid.uuid4(),
        campaign_id=campaign_id,
        agency_name="Test Agency",
        contact_email=f"{uuid.uuid4().hex}@example.com",
        icp_grade=icp_grade,
        state=state,
    )
    session.add(prospect)
    await session.commit()
    return prospect


async def _add_domain(
    session: AsyncSession,
    prospect_id: uuid.UUID,
    *,
    state: str = "pending",
    scan_attempts: int = 0,
    scan_id: uuid.UUID | None = None,
    updated_at: datetime | None = None,
) -> OutreachDomainRecord:
    domain = OutreachDomainRecord(
        domain_id=uuid.uuid4(),
        prospect_id=prospect_id,
        hostname=f"{uuid.uuid4().hex}.example.com",
        state=state,
        scan_attempts=scan_attempts,
        scan_id=scan_id,
    )
    session.add(domain)
    await session.commit()
    if updated_at is not None:
        await session.execute(
            OutreachDomainRecord.__table__.update()
            .where(OutreachDomainRecord.domain_id == domain.domain_id)
            .values(updated_at=updated_at)
        )
        await session.commit()
        await session.refresh(domain)
    return domain


async def _add_scan(
    session: AsyncSession,
    *,
    status: str,
    result: dict | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    created_at: datetime | None = None,
) -> ScanRecord:
    scan = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname="client.example.com",
        status=status,
        result=result,
        error_code=error_code,
        error_message=error_message,
    )
    session.add(scan)
    await session.commit()
    if created_at is not None:
        await session.execute(
            ScanRecord.__table__.update()
            .where(ScanRecord.scan_id == scan.scan_id)
            .values(created_at=created_at)
        )
        await session.commit()
        await session.refresh(scan)
    return scan


def _completed_result() -> dict:
    scan = make_completed_scan(is_complete=True)
    return stamp_schema_version(scan.model_dump(mode="json"))


def _completed_result_with_module_error(module_error: ModuleErrorCode) -> dict:
    from app.schemas import ModuleError

    modules = default_modules()
    modules.dns.status = ModuleStatus.ERROR
    modules.dns.data = None
    modules.dns.error = ModuleError(code=module_error, message="a safe generic message")
    scan = make_completed_scan(modules=modules, is_complete=False, incomplete_modules=["dns"])
    return stamp_schema_version(scan.model_dump(mode="json"))


# --- completed_domains_for_prospect ---


async def test_completed_domains_for_prospect_excludes_completed_partial(
    db_session: AsyncSession, campaign: OutreachCampaignRecord
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    completed = await _add_domain(db_session, prospect.prospect_id, state="completed")
    await _add_domain(db_session, prospect.prospect_id, state="completed_partial")
    await _add_domain(db_session, prospect.prospect_id, state="failed")

    result = await completed_domains_for_prospect(db_session, prospect.prospect_id)
    assert [d.domain_id for d in result] == [completed.domain_id]


# --- claim_and_start_domains: eligibility ---


async def test_claim_pending_domains_up_to_capacity(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    for _ in range(3):
        await _add_domain(db_session, prospect.prospect_id, state="pending")

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=2)
    assert claimed == 2
    assert len(arq_pool.enqueued) == 2

    domains = (
        (
            await db_session.execute(
                OutreachDomainRecord.__table__.select().where(
                    OutreachDomainRecord.prospect_id == prospect.prospect_id
                )
            )
        )
        .mappings()
        .all()
    )
    states = sorted(d["state"] for d in domains)
    assert states == ["pending", "running", "running"]


async def test_claim_transitions_prospect_to_scanning(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="pending")
    await _add_domain(db_session, prospect.prospect_id, state="pending")

    await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)

    await db_session.refresh(prospect)
    assert prospect.state == "scanning"


async def test_claim_skips_weak_prospects_by_default(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    weak = await _add_prospect(db_session, campaign.campaign_id, icp_grade="weak")
    await _add_domain(db_session, weak.prospect_id, state="pending")

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)
    assert claimed == 0


async def test_claim_includes_weak_prospects_when_flagged(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    campaign.include_weak_prospects = True
    await db_session.commit()
    weak = await _add_prospect(db_session, campaign.campaign_id, icp_grade="weak")
    await _add_domain(db_session, weak.prospect_id, state="pending")

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)
    assert claimed == 1


async def test_claim_respects_retry_backoff_not_yet_elapsed(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(
        db_session,
        prospect.prospect_id,
        state="retrying",
        scan_attempts=1,
        updated_at=datetime.now(UTC),  # just failed, backoff not elapsed
    )

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)
    assert claimed == 0


async def test_claim_picks_up_retrying_domain_once_backoff_elapsed(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    backoff = get_settings().outreach_retry_backoff_seconds
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(
        db_session,
        prospect.prospect_id,
        state="retrying",
        scan_attempts=1,
        updated_at=datetime.now(UTC) - timedelta(seconds=backoff + 5),
    )

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)
    assert claimed == 1


async def test_claim_picks_up_completed_partial_for_its_one_rescan(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    backoff = get_settings().outreach_retry_backoff_seconds
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    domain = await _add_domain(
        db_session,
        prospect.prospect_id,
        state="completed_partial",
        scan_attempts=1,
        updated_at=datetime.now(UTC) - timedelta(seconds=backoff + 5),
    )

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)
    assert claimed == 1
    await db_session.refresh(domain)
    assert domain.state == "running"
    assert domain.scan_attempts == 2


async def test_claim_does_not_rescan_completed_partial_a_second_time(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    """Spec: COMPLETED_PARTIAL gets exactly one re-scan, ever — not governed
    by OUTREACH_MAX_SCAN_RETRIES."""
    backoff = get_settings().outreach_retry_backoff_seconds
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(
        db_session,
        prospect.prospect_id,
        state="completed_partial",
        scan_attempts=2,  # already had its one re-scan
        updated_at=datetime.now(UTC) - timedelta(seconds=backoff + 5),
    )

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)
    assert claimed == 0


async def test_claim_raises_campaign_paused_error_when_campaign_is_paused(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    """Internal invariant, not the normal path (outreach_scan_tick never
    calls this for a paused campaign) — defense in depth if it ever did."""
    campaign.status = OutreachCampaignStatus.PAUSED.value
    await db_session.commit()
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(db_session, prospect.prospect_id, state="pending")

    with pytest.raises(CampaignPausedError):
        await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=5)


async def test_claim_zero_capacity_claims_nothing(
    db_session: AsyncSession,
    campaign: OutreachCampaignRecord,
    redis: _FakeRedis,
    arq_pool: _FakeArqPool,
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id)
    await _add_domain(db_session, prospect.prospect_id, state="pending")

    claimed = await claim_and_start_domains(db_session, redis, arq_pool, campaign, capacity=0)
    assert claimed == 0


# --- settle_running_domains / reconciliation ---


async def test_settle_completed_scan_marks_domain_completed(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(
        db_session, status=ScanStatus.COMPLETED.value, result=_completed_result()
    )
    domain = await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )

    settled = await settle_running_domains(db_session, redis, campaign)
    assert settled == 1
    await db_session.refresh(domain)
    assert domain.state == "completed"


async def test_settle_completed_but_incomplete_scan_marks_completed_partial_with_summary(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(
        db_session,
        status=ScanStatus.COMPLETED.value,
        result=_completed_result_with_module_error(ModuleErrorCode.MODULE_TIMEOUT),
    )
    domain = await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )

    await settle_running_domains(db_session, redis, campaign)
    await db_session.refresh(domain)
    assert domain.state == "completed_partial"
    assert domain.scan_error is not None
    assert "MODULE_TIMEOUT" in domain.scan_error


async def test_settle_failed_scan_retries_then_fails_after_three_attempts(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    """OUTREACH_MAX_SCAN_RETRIES=2 -> 3 total attempts before FAILED
    (CONTRACT.md §7.16's pinned-down reading)."""
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")

    for attempt, expected_state in ((1, "retrying"), (2, "retrying"), (3, "failed")):
        scan = await _add_scan(
            db_session,
            status=ScanStatus.FAILED.value,
            error_code=ErrorCode.SCAN_FAILED.value,
            error_message="'client.example.com' does not resolve.",
        )
        domain = await _add_domain(
            db_session,
            prospect.prospect_id,
            state="running",
            scan_attempts=attempt,
            scan_id=scan.scan_id,
        )
        await settle_running_domains(db_session, redis, campaign)
        await db_session.refresh(domain)
        assert domain.state == expected_state, f"attempt {attempt}"
        assert domain.scan_error == "'client.example.com' does not resolve."


async def test_settle_stale_still_running_scan_treated_as_crash(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    stale_at = datetime.now(UTC) - timedelta(
        seconds=get_settings().scan_timeout_seconds + 61
    )
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(db_session, status=ScanStatus.RUNNING.value, created_at=stale_at)
    domain = await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )

    settled = await settle_running_domains(db_session, redis, campaign)
    assert settled == 1
    await db_session.refresh(domain)
    assert domain.state == "retrying"
    lowered = (domain.scan_error or "").lower()
    assert "crash" in lowered or "stuck" in lowered


async def test_settle_leaves_genuinely_in_flight_scan_alone(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(db_session, status=ScanStatus.RUNNING.value)  # created just now
    domain = await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )

    settled = await settle_running_domains(db_session, redis, campaign)
    assert settled == 0
    await db_session.refresh(domain)
    assert domain.state == "running"  # untouched


async def test_settle_runs_for_paused_campaign_too(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    campaign.status = OutreachCampaignStatus.PAUSED.value
    await db_session.commit()
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(
        db_session, status=ScanStatus.COMPLETED.value, result=_completed_result()
    )
    domain = await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )

    settled = await settle_running_domains(db_session, redis, campaign)
    assert settled == 1
    await db_session.refresh(domain)
    assert domain.state == "completed"  # in-flight work still resolves while paused


# --- prospect roll-up ---


async def test_prospect_rolls_up_to_analyzing_with_one_completed_and_one_failed(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(
        db_session, status=ScanStatus.COMPLETED.value, result=_completed_result()
    )
    await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )
    await _add_domain(db_session, prospect.prospect_id, state="failed", scan_attempts=3)

    await settle_running_domains(db_session, redis, campaign)
    await db_session.refresh(prospect)
    assert prospect.state == "analyzing"


async def test_prospect_rolls_up_to_failed_when_no_domain_completed(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(
        db_session,
        status=ScanStatus.COMPLETED.value,
        result=_completed_result_with_module_error(ModuleErrorCode.CONNECTION_REFUSED),
    )
    await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )
    await _add_domain(db_session, prospect.prospect_id, state="failed", scan_attempts=3)

    await settle_running_domains(db_session, redis, campaign)
    await db_session.refresh(prospect)
    assert prospect.state == "failed"
    assert prospect.state_reason is not None
    assert "no domain reached COMPLETED" in prospect.state_reason


async def test_prospect_does_not_roll_up_while_a_domain_is_still_pending(
    db_session: AsyncSession, campaign: OutreachCampaignRecord, redis: _FakeRedis
) -> None:
    prospect = await _add_prospect(db_session, campaign.campaign_id, state="scanning")
    scan = await _add_scan(
        db_session, status=ScanStatus.COMPLETED.value, result=_completed_result()
    )
    await _add_domain(
        db_session, prospect.prospect_id, state="running", scan_attempts=1, scan_id=scan.scan_id
    )
    await _add_domain(db_session, prospect.prospect_id, state="pending")  # not started yet

    await settle_running_domains(db_session, redis, campaign)
    await db_session.refresh(prospect)
    assert prospect.state == "scanning"  # unchanged — still waiting on the pending one
