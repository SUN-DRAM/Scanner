"""Tests for the v2.8 admin dashboard: `GET /api/v1/admin/accounts` and
`GET /api/v1/admin/health` (contract §7.13). Token gate, derived signals,
filters, sorting, and the operational health report.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import (
    AlertEventRecord,
    MembershipRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
    ProspectBatchRecord,
    ProspectScanRecord,
    ScanRecord,
    SubscriptionRecord,
    UserRecord,
    WaitlistSignupRecord,
)
from app.redis_client import get_arq_pool, get_redis_client
from tests.conftest import FakeArqPool


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def admin_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    token = "test-admin-" + uuid.uuid4().hex
    monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()
    yield token
    get_settings.cache_clear()


def _auth(token: str) -> dict[str, str]:
    return {"X-Admin-Token": token}


class _Seeder:
    """Creates isolated orgs/users/monitors for one test and deletes exactly
    those rows afterwards — the shared `db_session` is a real database that
    persists between tests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.org_ids: list[uuid.UUID] = []
        self.user_ids: list[uuid.UUID] = []
        self.scan_ids: list[uuid.UUID] = []
        self.batch_ids: list[uuid.UUID] = []
        self.waitlist_ids: list[uuid.UUID] = []

    async def org(
        self,
        *,
        name: str | None = None,
        plan_code: str = "free",
        created_at: datetime | None = None,
    ) -> OrganisationRecord:
        org = OrganisationRecord(
            org_id=uuid.uuid4(),
            name=name or f"Org {uuid.uuid4().hex[:8]}",
            country="IN",
            currency="INR",
            plan_code=plan_code,
            timezone="Asia/Kolkata",
            quiet_hours_start="21:00",
            quiet_hours_end="08:00",
            digest_mode="digest",
            digest_hour=9,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(org)
        await self.session.flush()
        self.org_ids.append(org.org_id)
        return org

    async def owner(
        self,
        org: OrganisationRecord,
        *,
        email: str | None = None,
        last_login_at: datetime | None = None,
    ) -> UserRecord:
        user = UserRecord(
            user_id=uuid.uuid4(),
            email=email or f"{uuid.uuid4().hex[:10]}@example.com",
            email_verified=True,
            last_login_at=last_login_at,
            created_at=datetime.now(UTC),
        )
        self.session.add(user)
        await self.session.flush()
        self.user_ids.append(user.user_id)
        self.session.add(
            MembershipRecord(
                org_id=org.org_id,
                user_id=user.user_id,
                role="owner",
                joined_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return user

    async def monitor(
        self,
        org: OrganisationRecord,
        *,
        hostname: str | None = None,
        last_grade: str | None = None,
        last_scanned_at: datetime | None = None,
        cert_not_after: datetime | None = None,
        next_scan_at: datetime | None = None,
        state: str = "active",
    ) -> MonitoredHostnameRecord:
        record = MonitoredHostnameRecord(
            monitor_id=uuid.uuid4(),
            org_id=org.org_id,
            hostname=hostname or f"{uuid.uuid4().hex[:8]}.example.com",
            port=443,
            state=state,
            last_grade=last_grade,
            last_scanned_at=last_scanned_at,
            cert_not_after=cert_not_after,
            next_scan_at=next_scan_at,
            created_at=datetime.now(UTC),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def scheduler_scan(
        self, monitor: MonitoredHostnameRecord, *, created_at: datetime | None = None
    ) -> ScanRecord:
        """A scan as the scheduler would create it (app/monitors.py's
        create_monitor_scan_record): monitor-linked, no client IP hash."""
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=uuid.uuid4().hex[:12],
            hostname=monitor.hostname,
            port=monitor.port,
            status="completed",
            monitor_id=monitor.monitor_id,
            client_ip_hash=None,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def public_scan(
        self,
        *,
        created_at: datetime | None = None,
        hostname: str | None = None,
        monitor_id: uuid.UUID | None = None,
    ) -> ScanRecord:
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=uuid.uuid4().hex[:12],
            hostname=hostname or f"{uuid.uuid4().hex[:8]}.example.com",
            port=443,
            status="completed",
            monitor_id=monitor_id,
            client_ip_hash=None,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(record)
        await self.session.flush()
        self.scan_ids.append(record.scan_id)
        return record

    async def corrupted_scan(
        self,
        monitor: MonitoredHostnameRecord,
        *,
        overall_grade: str | None = "A",
        created_at: datetime | None = None,
    ) -> ScanRecord:
        """docs/urgent_scan_corruption.md Finding 4's exact shape: `status`
        'failed' with a non-null `overall_grade` -- only reachable by a scan
        completing successfully and then being overwritten afterward."""
        record = ScanRecord(
            scan_id=uuid.uuid4(),
            public_slug=uuid.uuid4().hex[:12],
            hostname=monitor.hostname,
            port=monitor.port,
            status="failed",
            overall_grade=overall_grade,
            overall_score=90,
            monitor_id=monitor.monitor_id,
            client_ip_hash=None,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(record)
        await self.session.flush()
        self.scan_ids.append(record.scan_id)
        return record

    async def prospect_batch_scan(self, scan: ScanRecord) -> None:
        batch = ProspectBatchRecord(batch_id=uuid.uuid4(), label="test batch")
        self.session.add(batch)
        await self.session.flush()
        self.batch_ids.append(batch.batch_id)
        self.session.add(
            ProspectScanRecord(
                id=uuid.uuid4(),
                batch_id=batch.batch_id,
                scan_id=scan.scan_id,
                hostname=scan.hostname,
            )
        )
        await self.session.flush()

    async def waitlist_signup(self, *, created_at: datetime | None = None) -> None:
        scan = await self.public_scan(created_at=created_at)
        record = WaitlistSignupRecord(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex[:10]}@example.com",
            hostname=scan.hostname,
            scan_id=scan.scan_id,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(record)
        await self.session.flush()
        self.waitlist_ids.append(record.id)

    async def alert(
        self,
        org: OrganisationRecord,
        monitor: MonitoredHostnameRecord,
        *,
        state: str = "sent",
        recipients: list[str] | None = None,
        subject: str = "x",
    ) -> AlertEventRecord:
        record = AlertEventRecord(
            alert_id=uuid.uuid4(),
            org_id=org.org_id,
            monitor_id=monitor.monitor_id,
            type="cert_expiry",
            state=state,
            severity="high",
            subject=subject,
            dedupe_key=uuid.uuid4().hex,
            scheduled_for=datetime.now(UTC),
            recipients=recipients if recipients is not None else [],
            payload={},
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def alert_sent(self, org: OrganisationRecord, monitor: MonitoredHostnameRecord) -> None:
        await self.alert(org, monitor, state="sent")

    async def commit(self) -> None:
        await self.session.commit()

    async def cleanup(self) -> None:
        # Prospect batches first: the ondelete=CASCADE FK clears prospect_scans,
        # freeing the scans they reference for the standalone-scan delete below.
        if self.batch_ids:
            await self.session.execute(
                delete(ProspectBatchRecord).where(ProspectBatchRecord.batch_id.in_(self.batch_ids))
            )
        if self.waitlist_ids:
            await self.session.execute(
                delete(WaitlistSignupRecord).where(WaitlistSignupRecord.id.in_(self.waitlist_ids))
            )
        for org_id in self.org_ids:
            monitor_ids = (
                (
                    await self.session.execute(
                        select(MonitoredHostnameRecord.monitor_id).where(
                            MonitoredHostnameRecord.org_id == org_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            await self.session.execute(
                delete(AlertEventRecord).where(AlertEventRecord.org_id == org_id)
            )
            if monitor_ids:
                await self.session.execute(
                    delete(ScanRecord).where(ScanRecord.monitor_id.in_(monitor_ids))
                )
            await self.session.execute(
                delete(MonitoredHostnameRecord).where(MonitoredHostnameRecord.org_id == org_id)
            )
            await self.session.execute(
                delete(SubscriptionRecord).where(SubscriptionRecord.org_id == org_id)
            )
            await self.session.execute(
                delete(MembershipRecord).where(MembershipRecord.org_id == org_id)
            )
            await self.session.execute(
                delete(OrganisationRecord).where(OrganisationRecord.org_id == org_id)
            )
        for user_id in self.user_ids:
            await self.session.execute(delete(UserRecord).where(UserRecord.user_id == user_id))
        if self.scan_ids:
            await self.session.execute(
                delete(ScanRecord).where(ScanRecord.scan_id.in_(self.scan_ids))
            )
        await self.session.commit()


@pytest.fixture
async def seed(db_session: AsyncSession) -> AsyncGenerator[_Seeder]:
    seeder = _Seeder(db_session)
    yield seeder
    await seeder.cleanup()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


@pytest.fixture
async def health_client(
    db_session: AsyncSession, redis_client: Redis
) -> AsyncGenerator[AsyncClient]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


@pytest.fixture
async def prospects_client(
    db_session: AsyncSession, fake_arq_pool: FakeArqPool
) -> AsyncGenerator[AsyncClient]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq_pool
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


# --- token gate ---


@pytest.mark.asyncio
async def test_accounts_rejects_missing_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/accounts")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_accounts_rejects_wrong_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/admin/accounts", headers={"X-Admin-Token": "not-the-token"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_accounts_rejects_when_admin_token_unset(client: AsyncClient) -> None:
    response = await client.get("/api/v1/admin/accounts", headers={"X-Admin-Token": "anything"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_accounts_accepts_token_query_param(client: AsyncClient, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/accounts", params={"token": admin_token})
    assert response.status_code == 200


# --- account rows ---


@pytest.mark.asyncio
async def test_accounts_row_carries_derived_signals(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org(name="Acme QA", plan_code="watch")
    await seed.owner(
        org,
        email="founder-qa@example.com",
        last_login_at=datetime.now(UTC) - timedelta(days=2),
    )
    monitor = await seed.monitor(
        org,
        last_grade="C",
        last_scanned_at=datetime.now(UTC) - timedelta(hours=3),
        cert_not_after=datetime.now(UTC) + timedelta(days=20),
    )
    await seed.alert_sent(org, monitor)
    await seed.commit()

    response = await client.get(
        "/api/v1/admin/accounts", headers=_auth(admin_token), params={"per_page": 100}
    )
    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["org_id"] == str(org.org_id))
    assert row["name"] == "Acme QA"
    assert row["primary_email"] == "founder-qa@example.com"
    assert row["plan_code"] == "watch"
    assert row["hostname_count"] == 1
    assert row["hostname_limit"] == 25
    assert row["worst_grade"] == "C"
    assert row["alerts_sent_count"] == 1
    assert row["health"] == "activated"
    assert row["is_paying"] is False
    assert row["soonest_expiry_days"] in (19, 20)
    assert row["last_login_relative"] == "2 days ago"


@pytest.mark.asyncio
async def test_accounts_health_filter_isolates_stalled(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    stalled = await seed.org(name="Stalled Co")
    await seed.owner(stalled, last_login_at=datetime.now(UTC) - timedelta(days=1))
    activated = await seed.org(name="Activated Co")
    await seed.owner(activated, last_login_at=datetime.now(UTC) - timedelta(hours=1))
    await seed.monitor(activated, last_grade="A")
    await seed.commit()

    response = await client.get(
        "/api/v1/admin/accounts",
        headers=_auth(admin_token),
        params={"health": "stalled", "per_page": 100},
    )
    items = response.json()["items"]
    ids = {item["org_id"] for item in items}
    assert str(stalled.org_id) in ids
    assert str(activated.org_id) not in ids
    assert all(item["health"] == "stalled" for item in items)


@pytest.mark.asyncio
async def test_accounts_plan_filter(client: AsyncClient, admin_token: str, seed: _Seeder) -> None:
    free_org = await seed.org(name="Free Co", plan_code="free")
    await seed.owner(free_org)
    watch_org = await seed.org(name="Watch Co", plan_code="watch")
    await seed.owner(watch_org)
    await seed.commit()

    response = await client.get(
        "/api/v1/admin/accounts",
        headers=_auth(admin_token),
        params={"plan": "watch", "per_page": 100},
    )
    ids = {item["org_id"] for item in response.json()["items"]}
    assert str(watch_org.org_id) in ids
    assert str(free_org.org_id) not in ids


@pytest.mark.asyncio
async def test_accounts_sort_oldest_first(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    # Dated ~13 months back in a 15-day window nothing else in the suite
    # touches, then filtered to exactly that window — so the assertion holds
    # regardless of how many other orgs the shared test database contains.
    older = await seed.org(name="Older", created_at=datetime.now(UTC) - timedelta(days=400))
    await seed.owner(older)
    newer = await seed.org(name="Newer", created_at=datetime.now(UTC) - timedelta(days=395))
    await seed.owner(newer)
    await seed.commit()

    window_start = (datetime.now(UTC) - timedelta(days=405)).date().isoformat()
    window_end = (datetime.now(UTC) - timedelta(days=390)).date().isoformat()
    response = await client.get(
        "/api/v1/admin/accounts",
        headers=_auth(admin_token),
        params={
            "sort": "oldest",
            "per_page": 100,
            "signed_up_after": window_start,
            "signed_up_before": window_end,
        },
    )
    order = [item["org_id"] for item in response.json()["items"]]
    assert order == [str(older.org_id), str(newer.org_id)]


@pytest.mark.asyncio
async def test_accounts_dormant_when_never_logged_in(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org(name="Ghost Co")
    await seed.owner(org, last_login_at=None)
    await seed.monitor(org, last_grade="B")
    await seed.commit()

    response = await client.get(
        "/api/v1/admin/accounts", headers=_auth(admin_token), params={"per_page": 100}
    )
    row = next(item for item in response.json()["items"] if item["org_id"] == str(org.org_id))
    assert row["health"] == "dormant"
    assert row["last_login_at"] is None
    assert row["last_login_relative"] is None


# --- health report ---


@pytest.mark.asyncio
async def test_health_report_shape(health_client: AsyncClient, admin_token: str) -> None:
    response = await health_client.get("/api/v1/admin/health", headers=_auth(admin_token))
    assert response.status_code == 200
    body = response.json()
    assert body["postgres"] == "ok"
    assert body["redis"] == "ok"
    assert set(body["scans_24h"]) == {
        "completed",
        "failed",
        "queued",
        "running",
        "stuck",
    }
    assert set(body["scheduler"]) == {
        "monitors_due",
        "monitors_overdue",
        "monitors_overdue_1h",
        "last_successful_run_at",
    }
    assert body["worker"]["memory_mb"] is None
    assert body["anomalous_failed_scans_24h"] == 0


@pytest.mark.asyncio
async def test_health_report_flags_overdue_monitor(
    health_client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org()
    await seed.owner(org)
    await seed.monitor(org, next_scan_at=datetime.now(UTC) - timedelta(hours=2), state="active")
    await seed.commit()

    response = await health_client.get("/api/v1/admin/health", headers=_auth(admin_token))
    scheduler = response.json()["scheduler"]
    assert scheduler["monitors_overdue_1h"] >= 1
    assert scheduler["monitors_due"] >= 1


@pytest.mark.asyncio
async def test_health_flags_a_scan_completed_then_overwritten_as_failed(
    health_client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    """docs/urgent_scan_corruption.md Finding 4 / Step 4: the live canary
    for this exact bug (or another with the same shape) recurring."""
    org = await seed.org()
    await seed.owner(org)
    monitor = await seed.monitor(org)
    await seed.corrupted_scan(monitor)
    await seed.commit()

    response = await health_client.get("/api/v1/admin/health", headers=_auth(admin_token))
    assert response.json()["anomalous_failed_scans_24h"] >= 1


@pytest.mark.asyncio
async def test_health_ignores_an_honest_failed_scan(
    health_client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    """A genuinely failed scan (no grade, the only shape `_mark_failed`
    actually produces) must never trip the anomaly count."""
    org = await seed.org()
    await seed.owner(org)
    monitor = await seed.monitor(org)
    await seed.corrupted_scan(monitor, overall_grade=None)
    await seed.commit()

    response = await health_client.get("/api/v1/admin/health", headers=_auth(admin_token))
    assert response.json()["anomalous_failed_scans_24h"] == 0


@pytest.mark.asyncio
async def test_health_last_successful_run_tracks_scheduler_scans(
    health_client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org()
    await seed.owner(org)
    monitor = await seed.monitor(org)
    marker = datetime.now(UTC) + timedelta(days=1)
    await seed.scheduler_scan(monitor, created_at=marker)
    await seed.commit()

    response = await health_client.get("/api/v1/admin/health", headers=_auth(admin_token))
    last_run = response.json()["scheduler"]["last_successful_run_at"]
    assert last_run is not None
    # The future-dated marker scan is the newest scheduler-originated scan.
    assert last_run == marker.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.asyncio
async def test_health_rejects_missing_token(health_client: AsyncClient, admin_token: str) -> None:
    response = await health_client.get("/api/v1/admin/health")
    assert response.status_code == 403


# --- account detail ---


@pytest.mark.asyncio
async def test_account_detail_returns_full_shape(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org(name="Detail Co", plan_code="watch")
    await seed.owner(org, email="owner-detail@example.com")
    monitor = await seed.monitor(org, hostname="detail.example.com", last_grade="B")
    await seed.scheduler_scan(monitor)
    await seed.alert(org, monitor, state="sent", recipients=["ops@example.com"])
    await seed.commit()

    response = await client.get(f"/api/v1/admin/accounts/{org.org_id}", headers=_auth(admin_token))
    assert response.status_code == 200
    body = response.json()
    assert body["org"]["org_id"] == str(org.org_id)
    assert body["org"]["name"] == "Detail Co"
    assert [m["email"] for m in body["members"]] == ["owner-detail@example.com"]
    assert body["subscription"] is None
    assert body["invoices"] == []
    assert [m["hostname"] for m in body["monitors"]] == ["detail.example.com"]
    assert body["failed_alerts"] == []
    assert len(body["recent_alerts"]) == 1
    assert body["recent_alerts"][0]["monitor_hostname"] == "detail.example.com"
    assert body["recent_alerts"][0]["recipients"] == ["ops@example.com"]
    assert len(body["recent_scans"]) == 1
    assert body["recent_scans"][0]["hostname"] == "detail.example.com"
    assert body["recent_scans"][0]["share_url"].endswith(
        f"/scan/{body['recent_scans'][0]['public_slug']}"
    )


@pytest.mark.asyncio
async def test_account_detail_surfaces_failed_alerts_separately(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org()
    await seed.owner(org)
    monitor = await seed.monitor(org, hostname="broken.example.com")
    failed = await seed.alert(org, monitor, state="failed")
    await seed.alert(org, monitor, state="sent")
    await seed.commit()

    response = await client.get(f"/api/v1/admin/accounts/{org.org_id}", headers=_auth(admin_token))
    body = response.json()
    failed_ids = {a["alert_id"] for a in body["failed_alerts"]}
    recent_ids = {a["alert_id"] for a in body["recent_alerts"]}
    assert failed_ids == {str(failed.alert_id)}
    # A failed alert also stays in the full recent list, not filtered out.
    assert str(failed.alert_id) in recent_ids
    assert len(recent_ids) == 2


@pytest.mark.asyncio
async def test_account_detail_404_for_unknown_org(client: AsyncClient, admin_token: str) -> None:
    response = await client.get(
        f"/api/v1/admin/accounts/{uuid.uuid4()}", headers=_auth(admin_token)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_account_detail_404_for_malformed_org_id(
    client: AsyncClient, admin_token: str
) -> None:
    response = await client.get("/api/v1/admin/accounts/not-a-uuid", headers=_auth(admin_token))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_account_detail_rejects_missing_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.get(f"/api/v1/admin/accounts/{uuid.uuid4()}")
    assert response.status_code == 403


# --- funnel ---


def _day_value(series: list[dict[str, str | int]], target: str) -> int:
    for point in series:
        if point["date"] == target:
            return int(point["value"])
    raise AssertionError(f"{target} not in series")


@pytest.mark.asyncio
async def test_funnel_report_shape(client: AsyncClient, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 30
    assert set(body["series"]) == {
        "scans_total",
        "scans_anonymous",
        "scans_logged_in",
        "unique_hostnames",
        "waitlist_signups",
    }
    for points in body["series"].values():
        assert len(points) == 30
        assert all({"date", "value"} == set(p) for p in points)
    assert set(body["rates"]) == {
        "scan_to_waitlist",
        "waitlist_to_account",
        "account_to_activation",
        "account_to_paid",
    }


@pytest.mark.asyncio
async def test_funnel_counts_and_splits_scans_by_day(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    org = await seed.org()
    monitor = await seed.monitor(org)
    day = datetime.now(UTC) - timedelta(days=5)
    day_iso = day.date().isoformat()

    before = (await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))).json()["series"]
    await seed.public_scan(created_at=day, hostname="a.example.com")
    await seed.public_scan(created_at=day, hostname="b.example.com")
    await seed.public_scan(created_at=day, hostname="a.example.com", monitor_id=monitor.monitor_id)
    await seed.commit()
    after = (await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))).json()["series"]

    assert (
        _day_value(after["scans_total"], day_iso) - _day_value(before["scans_total"], day_iso) == 3
    )
    assert (
        _day_value(after["scans_anonymous"], day_iso)
        - _day_value(before["scans_anonymous"], day_iso)
        == 2
    )
    assert (
        _day_value(after["scans_logged_in"], day_iso)
        - _day_value(before["scans_logged_in"], day_iso)
        == 1
    )


@pytest.mark.asyncio
async def test_funnel_excludes_prospect_scans(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    day = datetime.now(UTC) - timedelta(days=3)
    day_iso = day.date().isoformat()

    before = (await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))).json()["series"]
    scan = await seed.public_scan(created_at=day)
    await seed.prospect_batch_scan(scan)
    await seed.commit()
    after = (await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))).json()["series"]

    assert _day_value(after["scans_total"], day_iso) == _day_value(before["scans_total"], day_iso)


@pytest.mark.asyncio
async def test_funnel_counts_waitlist_signups_by_day(
    client: AsyncClient, admin_token: str, seed: _Seeder
) -> None:
    day = datetime.now(UTC) - timedelta(days=7)
    day_iso = day.date().isoformat()

    before = (await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))).json()["series"]
    await seed.waitlist_signup(created_at=day)
    await seed.commit()
    after = (await client.get("/api/v1/admin/funnel", headers=_auth(admin_token))).json()["series"]

    assert (
        _day_value(after["waitlist_signups"], day_iso)
        - _day_value(before["waitlist_signups"], day_iso)
        == 1
    )


@pytest.mark.asyncio
async def test_funnel_rejects_missing_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/funnel")
    assert response.status_code == 403


# --- prospects ---


async def _delete_batch(session: AsyncSession, batch_id: str) -> None:
    """The batch's prospect_scans go via ON DELETE CASCADE; delete the
    underlying scans afterwards so nothing is left behind."""
    scan_ids = (
        (
            await session.execute(
                select(ProspectScanRecord.scan_id).where(
                    ProspectScanRecord.batch_id == uuid.UUID(batch_id)
                )
            )
        )
        .scalars()
        .all()
    )
    await session.execute(
        delete(ProspectBatchRecord).where(ProspectBatchRecord.batch_id == uuid.UUID(batch_id))
    )
    if scan_ids:
        await session.execute(delete(ScanRecord).where(ScanRecord.scan_id.in_(scan_ids)))
    await session.commit()


@pytest.mark.asyncio
async def test_prospect_batch_create_list_and_detail(
    prospects_client: AsyncClient,
    admin_token: str,
    fake_arq_pool: FakeArqPool,
    db_session: AsyncSession,
) -> None:
    response = await prospects_client.post(
        "/api/v1/admin/prospects",
        headers=_auth(admin_token),
        json={
            "label": "Redwing Agency",
            "hostnames": ["a-portfolio.example.com", "b-portfolio.example.com", "not a host"],
        },
    )
    assert response.status_code == 202
    body = response.json()
    batch_id = body["batch_id"]
    try:
        assert body["label"] == "Redwing Agency"
        assert body["hostname_count"] == 2
        assert body["scans_pending"] == 2
        accepted = [item for item in body["items"] if item["accepted"]]
        rejected = [item for item in body["items"] if not item["accepted"]]
        assert len(accepted) == 2
        assert rejected[0]["reason_code"] == "INVALID_HOSTNAME"
        assert accepted[0]["status"] == "queued"
        assert accepted[0]["share_url"].endswith(f"/scan/{accepted[0]['public_slug']}")
        assert sum(1 for fn, _ in fake_arq_pool.enqueued if fn == "run_scan_job") == 2

        scan_ids = {item["scan_id"] for item in accepted}
        for scan_id in scan_ids:
            scan = await db_session.get(ScanRecord, uuid.UUID(scan_id))
            assert scan is not None
            assert scan.monitor_id is None  # never a monitored hostname

        listed = await prospects_client.get(
            "/api/v1/admin/prospects", headers=_auth(admin_token), params={"per_page": 100}
        )
        assert batch_id in {row["batch_id"] for row in listed.json()["items"]}

        detail = (
            await prospects_client.get(
                f"/api/v1/admin/prospects/{batch_id}", headers=_auth(admin_token)
            )
        ).json()
        assert detail["hostname_count"] == 2
        assert all(item["accepted"] for item in detail["items"])
        assert {item["scan_id"] for item in detail["items"]} == scan_ids
    finally:
        await _delete_batch(db_session, batch_id)


@pytest.mark.asyncio
async def test_prospect_batch_rejects_blocked_target_but_still_creates(
    prospects_client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    response = await prospects_client.post(
        "/api/v1/admin/prospects",
        headers=_auth(admin_token),
        json={"label": "Blocked test", "hostnames": ["10.0.0.5", "good-host.example.com"]},
    )
    assert response.status_code == 202
    body = response.json()
    try:
        blocked = next(item for item in body["items"] if item["hostname"] == "10.0.0.5")
        assert blocked["accepted"] is False
        assert blocked["reason_code"] == "BLOCKED_TARGET"
        assert body["hostname_count"] == 1
    finally:
        await _delete_batch(db_session, body["batch_id"])


@pytest.mark.asyncio
async def test_prospect_batch_over_500_rejected(
    prospects_client: AsyncClient, admin_token: str
) -> None:
    response = await prospects_client.post(
        "/api/v1/admin/prospects",
        headers=_auth(admin_token),
        json={"label": "Too big", "hostnames": [f"h{n}.example.com" for n in range(501)]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_prospect_batch_404_for_unknown_and_malformed(
    prospects_client: AsyncClient, admin_token: str
) -> None:
    unknown = await prospects_client.get(
        f"/api/v1/admin/prospects/{uuid.uuid4()}", headers=_auth(admin_token)
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "NOT_FOUND"
    malformed = await prospects_client.get(
        "/api/v1/admin/prospects/nope", headers=_auth(admin_token)
    )
    assert malformed.status_code == 404


@pytest.mark.asyncio
async def test_prospect_batch_csv_export(
    prospects_client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    created = await prospects_client.post(
        "/api/v1/admin/prospects",
        headers=_auth(admin_token),
        json={"label": "CSV / Batch", "hostnames": ["csv-host.example.com"]},
    )
    batch_id = created.json()["batch_id"]
    try:
        response = await prospects_client.get(
            f"/api/v1/admin/prospects/{batch_id}/export", headers=_auth(admin_token)
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment; filename=")
        assert "prospects-csv-batch.csv" in disposition
        header, *rows = response.text.splitlines()
        assert header == "label,hostname,grade,days_to_expiry,cert_lifetime_days,share_url"
        assert any("csv-host.example.com" in row for row in rows)
    finally:
        await _delete_batch(db_session, batch_id)


@pytest.mark.asyncio
async def test_prospects_reject_missing_token(
    prospects_client: AsyncClient, admin_token: str
) -> None:
    assert (await prospects_client.get("/api/v1/admin/prospects")).status_code == 403
    post = await prospects_client.post(
        "/api/v1/admin/prospects", json={"label": "x", "hostnames": ["h.example.com"]}
    )
    assert post.status_code == 403


# --- daily digest ---


@pytest.fixture
def digest_email(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    address = "founder@example.com"
    monkeypatch.setenv("ADMIN_DIGEST_EMAIL", address)
    get_settings.cache_clear()
    yield address
    get_settings.cache_clear()


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


@pytest.mark.asyncio
async def test_digest_noop_when_email_unset(db_session: AsyncSession) -> None:
    from app.admin.digest import send_admin_digest

    get_settings.cache_clear()
    sender = _FakeSender()
    assert await send_admin_digest(db_session, sender) is False
    assert sender.sent == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_digest_sends_and_renders(
    db_session: AsyncSession, digest_email: str, seed: _Seeder
) -> None:
    from app.admin.digest import send_admin_digest

    org = await seed.org()
    await seed.owner(org)
    await seed.monitor(org)
    await seed.commit()

    sender = _FakeSender()
    assert await send_admin_digest(db_session, sender) is True
    assert len(sender.sent) == 1
    message = sender.sent[0]
    assert message["to"] == digest_email
    assert message["subject"] == "SUN-DRAM daily digest"
    for label in ("New signups", "Hostnames added", "Alerts failed", "Monitors overdue >1h"):
        assert label in message["text"]
