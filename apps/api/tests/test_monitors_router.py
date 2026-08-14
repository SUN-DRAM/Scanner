"""HTTP-level tests for /api/v1/monitors... (contract §7.8): role
enforcement, duplicate/quota rejection, cross-org 404, bulk accept/reject,
and the manual re-scan rate limit — against a real Postgres and Redis.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncGenerator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.enums import ScanStatus
from app.main import app
from app.models import ScanRecord
from app.notify.email import get_email_sender
from app.ratelimit import hash_for_bucket
from app.redis_client import get_arq_pool, get_redis_client
from tests.conftest import FakeArqPool

_CODE_PATTERN = re.compile(r"\b(\d{6})\b")


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


def _extract_code(sender: FakeEmailSender) -> str:
    match = _CODE_PATTERN.search(sender.sent[-1]["text"])
    assert match is not None
    return match.group(1)


def _test_settings() -> Settings:
    return Settings(SESSION_SECRET="test-secret", CORS_ORIGINS="http://test")


def _random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def _random_hostname() -> str:
    return f"{uuid.uuid4().hex}.example.com"


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def fake_arq_pool() -> FakeArqPool:
    return FakeArqPool()


@pytest.fixture
def _wired_app(
    db_session: AsyncSession,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
    fake_arq_pool: FakeArqPool,
) -> Iterator[None]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_settings] = _test_settings
    app.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq_pool
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def _reset_otp_ip_rate_limit(redis_client: Redis) -> AsyncGenerator[None]:
    # See test_auth_router.py's fixture of the same name: every test here
    # logs in at least once, and ASGITransport reports every in-process
    # request as 127.0.0.1, so without this the shared per-IP OTP rate
    # limit bucket (10/hour, §7.6) eventually fails an unrelated test.
    yield
    await redis_client.delete(f"ratelimit:otp:ip:{hash_for_bucket('127.0.0.1')}")


async def _new_client(_wired_app: None) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _login(client: AsyncClient, fake_email_sender: FakeEmailSender, email: str) -> dict:
    await client.post("/api/v1/auth/otp/request", json={"email": email})
    code = _extract_code(fake_email_sender)
    response = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
async def owner_client(
    _wired_app: None, fake_email_sender: FakeEmailSender, redis_client: Redis
) -> AsyncGenerator[AsyncClient]:
    client = await _new_client(_wired_app)
    await _login(client, fake_email_sender, _random_email())
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_owner_can_create_list_get_update_and_delete_a_monitor(
    owner_client: AsyncClient,
) -> None:
    hostname = _random_hostname()
    create_response = await owner_client.post(
        "/api/v1/monitors", json={"hostname": hostname, "port": 443, "label": "Prod"}
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["hostname"] == hostname
    assert body["port"] == 443
    assert body["state"] == "active"
    assert body["label"] == "Prod"
    assert body["days_until_expiry"] is None
    monitor_id = body["monitor_id"]

    list_response = await owner_client.get("/api/v1/monitors")
    assert list_response.status_code == 200
    assert any(item["monitor_id"] == monitor_id for item in list_response.json()["items"])

    get_response = await owner_client.get(f"/api/v1/monitors/{monitor_id}")
    assert get_response.status_code == 200
    assert get_response.json()["hostname"] == hostname

    patch_response = await owner_client.patch(
        f"/api/v1/monitors/{monitor_id}", json={"label": "Renamed", "state": "paused"}
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["label"] == "Renamed"
    assert patch_response.json()["state"] == "paused"

    delete_response = await owner_client.delete(f"/api/v1/monitors/{monitor_id}")
    assert delete_response.status_code == 204

    missing_response = await owner_client.get(f"/api/v1/monitors/{monitor_id}")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_duplicate_hostname_and_port_is_rejected(owner_client: AsyncClient) -> None:
    hostname = _random_hostname()
    first = await owner_client.post("/api/v1/monitors", json={"hostname": hostname, "port": 443})
    assert first.status_code == 201

    second = await owner_client.post("/api/v1/monitors", json={"hostname": hostname, "port": 443})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_HOSTNAME"

    # Same hostname, different port: a distinct monitoring target (§7.8).
    different_port = await owner_client.post(
        "/api/v1/monitors", json={"hostname": hostname, "port": 8443}
    )
    assert different_port.status_code == 201


@pytest.mark.asyncio
async def test_quota_exceeded_returns_current_limit_plan_and_upgrade_target(
    owner_client: AsyncClient,
) -> None:
    # A brand-new org is on the free plan — limit 3 (app/plans.py / §5.1).
    for _ in range(3):
        response = await owner_client.post(
            "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
        )
        assert response.status_code == 201

    over_limit = await owner_client.post(
        "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
    )
    assert over_limit.status_code == 402
    body = over_limit.json()
    assert body["error"]["code"] == "QUOTA_EXCEEDED"
    assert body["error"]["details"] == {
        "current": 3,
        "limit": 3,
        "plan_code": "free",
        "upgrade_to": "watch",
    }


@pytest.mark.asyncio
async def test_member_can_read_but_gets_403_on_every_write(
    owner_client: AsyncClient,
    _wired_app: None,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    member_email = _random_email()
    invite_response = await owner_client.post(
        "/api/v1/orgs/current/members", json={"email": member_email, "role": "member"}
    )
    assert invite_response.status_code == 201

    hostname = _random_hostname()
    create_response = await owner_client.post(
        "/api/v1/monitors", json={"hostname": hostname, "port": 443}
    )
    monitor_id = create_response.json()["monitor_id"]

    member_client = await _new_client(_wired_app)
    try:
        await _login(member_client, fake_email_sender, member_email)

        list_response = await member_client.get("/api/v1/monitors")
        assert list_response.status_code == 200

        get_response = await member_client.get(f"/api/v1/monitors/{monitor_id}")
        assert get_response.status_code == 200

        create_attempt = await member_client.post(
            "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
        )
        assert create_attempt.status_code == 403

        patch_attempt = await member_client.patch(
            f"/api/v1/monitors/{monitor_id}", json={"label": "Hijacked"}
        )
        assert patch_attempt.status_code == 403

        delete_attempt = await member_client.delete(f"/api/v1/monitors/{monitor_id}")
        assert delete_attempt.status_code == 403

        bulk_attempt = await member_client.post(
            "/api/v1/monitors/bulk", json={"hostnames": [_random_hostname()]}
        )
        assert bulk_attempt.status_code == 403

        scan_attempt = await member_client.post(f"/api/v1/monitors/{monitor_id}/scan")
        assert scan_attempt.status_code == 403
    finally:
        await member_client.aclose()


@pytest.mark.asyncio
async def test_a_cross_org_monitor_id_returns_404_not_403(
    owner_client: AsyncClient,
    _wired_app: None,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    create_response = await owner_client.post(
        "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
    )
    monitor_id = create_response.json()["monitor_id"]

    other_owner_client = await _new_client(_wired_app)
    try:
        await _login(other_owner_client, fake_email_sender, _random_email())

        get_response = await other_owner_client.get(f"/api/v1/monitors/{monitor_id}")
        assert get_response.status_code == 404
        assert get_response.json()["error"]["code"] == "NOT_FOUND"

        delete_response = await other_owner_client.delete(f"/api/v1/monitors/{monitor_id}")
        assert delete_response.status_code == 404
    finally:
        await other_owner_client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_reports_per_row_acceptance_and_rejection(
    owner_client: AsyncClient,
) -> None:
    existing = _random_hostname()
    await owner_client.post("/api/v1/monitors", json={"hostname": existing, "port": 443})

    fresh_a = _random_hostname()
    fresh_b = f"{_random_hostname()}:8443"

    response = await owner_client.post(
        "/api/v1/monitors/bulk",
        json={"hostnames": [fresh_a, fresh_b, existing, "not a valid host"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 2

    by_hostname = {row["hostname"]: row for row in body["results"]}
    assert by_hostname[fresh_a]["accepted"] is True
    assert by_hostname[fresh_a]["monitor"]["port"] == 443
    assert by_hostname[fresh_b]["accepted"] is True
    assert by_hostname[fresh_b]["monitor"]["port"] == 8443
    assert by_hostname[existing]["accepted"] is False
    assert by_hostname[existing]["reason_code"] == "DUPLICATE_HOSTNAME"
    assert by_hostname["not a valid host"]["accepted"] is False
    assert by_hostname["not a valid host"]["reason_code"] == "INVALID_HOSTNAME"


@pytest.mark.asyncio
async def test_bulk_create_rejects_more_than_100_hostnames(owner_client: AsyncClient) -> None:
    hostnames = [_random_hostname() for _ in range(101)]
    response = await owner_client.post("/api/v1/monitors/bulk", json={"hostnames": hostnames})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_bulk_create_stops_accepting_once_quota_is_exhausted(
    owner_client: AsyncClient,
) -> None:
    # Free plan limit is 3 (app/plans.py) — 5 fresh hostnames in one batch
    # should accept exactly 3 and reject the rest as QUOTA_EXCEEDED, in order.
    hostnames = [_random_hostname() for _ in range(5)]
    response = await owner_client.post("/api/v1/monitors/bulk", json={"hostnames": hostnames})
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 3
    assert body["rejected_count"] == 2
    accepted_flags = [row["accepted"] for row in body["results"]]
    assert accepted_flags == [True, True, True, False, False]
    assert body["results"][3]["reason_code"] == "QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_manual_scan_enqueues_a_job_and_rate_limits_a_second_call(
    owner_client: AsyncClient, fake_arq_pool: FakeArqPool
) -> None:
    create_response = await owner_client.post(
        "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
    )
    monitor_id = create_response.json()["monitor_id"]

    first_scan = await owner_client.post(f"/api/v1/monitors/{monitor_id}/scan")
    assert first_scan.status_code == 202
    body = first_scan.json()
    assert body["status"] == "queued"
    assert body["cached"] is False
    assert len(fake_arq_pool.enqueued) == 1
    assert fake_arq_pool.enqueued[0][0] == "run_scan_job"

    second_scan = await owner_client.post(f"/api/v1/monitors/{monitor_id}/scan")
    assert second_scan.status_code == 429
    assert second_scan.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_history_returns_the_grade_and_score_timeline_newest_first(
    owner_client: AsyncClient, db_session: AsyncSession
) -> None:
    create_response = await owner_client.post(
        "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
    )
    monitor_id = uuid.UUID(create_response.json()["monitor_id"])

    older = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname="irrelevant.example.com",
        port=443,
        status=ScanStatus.COMPLETED.value,
        overall_grade="B",
        overall_score=80,
        monitor_id=monitor_id,
    )
    newer = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname="irrelevant.example.com",
        port=443,
        status=ScanStatus.COMPLETED.value,
        overall_grade="A",
        overall_score=96,
        monitor_id=monitor_id,
    )
    db_session.add(older)
    await db_session.commit()
    db_session.add(newer)
    await db_session.commit()

    response = await owner_client.get(f"/api/v1/monitors/{monitor_id}/history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["grade"] for item in body["items"]] == ["A", "B"]
    assert body["items"][0]["scan_id"] == str(newer.scan_id)
    assert body["items"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_history_for_a_cross_org_monitor_id_returns_404(
    owner_client: AsyncClient,
    _wired_app: None,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    other_owner_client = await _new_client(_wired_app)
    try:
        await _login(other_owner_client, fake_email_sender, _random_email())
        create_response = await other_owner_client.post(
            "/api/v1/monitors", json={"hostname": _random_hostname(), "port": 443}
        )
        monitor_id = create_response.json()["monitor_id"]

        response = await owner_client.get(f"/api/v1/monitors/{monitor_id}/history")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await other_owner_client.aclose()
