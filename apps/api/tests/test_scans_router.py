"""Request/response shape tests for `POST /api/v1/scans`,
`GET /api/v1/scans/{scan_id}`, and `GET /api/v1/scans/slug/{public_slug}`
(contract §7), against a real Postgres + Redis.

Run via `docker compose exec api pytest` — `db_session` and `redis_client`
(tests/conftest.py) skip gracefully when those aren't reachable, the same
pattern already used by test_ratelimit.py and test_orchestrator.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.enums import ScanStatus
from app.main import app
from app.models import ScanRecord
from app.redis_client import get_arq_pool, get_redis_client
from tests.conftest import FakeArqPool


@pytest.fixture
def _wired_app(
    db_session: AsyncSession, redis_client: Redis, fake_arq_pool: FakeArqPool
) -> Iterator[None]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq_pool
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client_ip() -> str:
    # A fresh synthetic IP per test, not the real TestClient peer address:
    # the rate limiter buckets by client IP in real, persistent Redis (not
    # reset between test runs), so a shared IP across every test in this
    # file would let one test's quota usage leak into another's.
    return f"203.0.113.{uuid.uuid4().int % 250}"


@pytest.fixture
async def client(_wired_app: None, client_ip: str) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app, client=(client_ip, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def _test_hostname() -> str:
    return f"test-{uuid.uuid4().hex}.example.com"


async def _cleanup(db_session: AsyncSession, hostname: str) -> None:
    await db_session.execute(delete(ScanRecord).where(ScanRecord.hostname == hostname))
    await db_session.commit()


@pytest.mark.asyncio
async def test_post_scans_returns_202_and_enqueues_a_job(
    client: AsyncClient, db_session: AsyncSession, fake_arq_pool: FakeArqPool
) -> None:
    hostname = _test_hostname()
    try:
        response = await client.post("/api/v1/scans", json={"hostname": hostname})
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["cached"] is False
        assert body["poll_url"] == f"/api/v1/scans/{body['scan_id']}"
        assert body["share_url"].endswith(f"/scan/{body['public_slug']}")
        assert len(body["public_slug"]) == 12
        uuid.UUID(body["scan_id"])  # does not raise
        assert fake_arq_pool.enqueued == [("run_scan_job", (body["scan_id"],))]
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_post_scans_defaults_port_to_443(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    try:
        response = await client.post("/api/v1/scans", json={"hostname": f"HTTPS://{hostname}/x"})
        assert response.status_code == 202
        record = await db_session.get(ScanRecord, uuid.UUID(response.json()["scan_id"]))
        assert record is not None
        assert record.hostname == hostname
        assert record.port == 443
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_post_scans_rejects_invalid_hostname(client: AsyncClient) -> None:
    response = await client.post("/api/v1/scans", json={"hostname": "not a hostname"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HOSTNAME"
    assert "request_id" in response.json()["error"]


@pytest.mark.asyncio
async def test_post_scans_rejects_disallowed_port(client: AsyncClient) -> None:
    response = await client.post("/api/v1/scans", json={"hostname": "example.com", "port": 22})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BLOCKED_TARGET"


@pytest.mark.asyncio
async def test_post_scans_rejects_private_address_target(
    client: AsyncClient, redis_client: Redis
) -> None:
    # Rate limiting (§10 rule 7) runs before the block check deliberately —
    # otherwise probing the SSRF guard would itself be a free, unthrottled
    # request. "localhost" is a fixed denylist string (STATIC_HOST_DENYLIST
    # in safety.py), reused across every run of this test against a real,
    # persistent Redis, so its hostname bucket is reset first to keep this
    # test from eventually tripping RATE_LIMITED instead of BLOCKED_TARGET.
    from app.ratelimit import hash_for_bucket

    await redis_client.delete(f"ratelimit:hostname:{hash_for_bucket('localhost')}")

    response = await client.post("/api/v1/scans", json={"hostname": "localhost"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BLOCKED_TARGET"


@pytest.mark.asyncio
async def test_post_scans_rate_limits_per_hostname(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    hostname = _test_hostname()
    try:
        # RATE_LIMIT_PER_HOSTNAME_PER_HOUR defaults to 6 (contract §4).
        for _ in range(6):
            created = await client.post("/api/v1/scans", json={"hostname": hostname})
            assert created.status_code == 202

        limited = await client.post("/api/v1/scans", json={"hostname": hostname})
        assert limited.status_code == 429
        body = limited.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert body["error"]["details"]["retry_after_seconds"] > 0
    finally:
        from app.ratelimit import hash_for_bucket

        await redis_client.delete(f"ratelimit:hostname:{hash_for_bucket(hostname)}")
        await redis_client.delete(f"ratelimit:ip:{hash_for_bucket(client_ip)}")
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_post_scans_returns_cached_result_for_a_recent_completed_scan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=ScanStatus.COMPLETED.value,
        overall_grade="A",
        overall_score=95,
        headline="Clean result. Nothing to fix.",
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    try:
        response = await client.post("/api/v1/scans", json={"hostname": hostname})
        assert response.status_code == 200
        body = response.json()
        assert body["cached"] is True
        assert body["scan_id"] == str(record.scan_id)
        assert body["public_slug"] == record.public_slug
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_post_scans_ignores_a_completed_scan_outside_the_cache_ttl(
    client: AsyncClient, db_session: AsyncSession, fake_arq_pool: FakeArqPool
) -> None:
    hostname = _test_hostname()
    stale = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=ScanStatus.COMPLETED.value,
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(stale)
    await db_session.commit()
    stale.created_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    try:
        response = await client.post("/api/v1/scans", json={"hostname": hostname})
        assert response.status_code == 202
        assert response.json()["cached"] is False
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_get_scan_by_id_returns_pending_shape_for_a_queued_scan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=ScanStatus.QUEUED.value,
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    try:
        response = await client.get(f"/api/v1/scans/{record.scan_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        assert body["overall_grade"] is None
        assert body["overall_score"] is None
        assert body["headline"] is None
        assert body["counts"] is None
        assert body["findings"] == []
        assert set(body["modules"].keys()) == {
            "certificate",
            "chain",
            "tls",
            "dns",
            "email_auth",
            "headers",
            "readiness",
        }
        assert all(value is None for value in body["modules"].values())
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_get_scan_by_id_returns_404_for_unknown_id(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/scans/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_scan_by_id_returns_404_for_a_malformed_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/scans/not-a-uuid")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_scan_by_slug_returns_the_matching_scan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    slug = uuid.uuid4().hex[:12]
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=slug,
        hostname=hostname,
        port=443,
        status=ScanStatus.RUNNING.value,
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    try:
        response = await client.get(f"/api/v1/scans/slug/{slug}")
        assert response.status_code == 200
        body = response.json()
        assert body["scan_id"] == str(record.scan_id)
        assert body["status"] == "running"
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_get_scan_by_slug_returns_404_for_unknown_slug(client: AsyncClient) -> None:
    response = await client.get("/api/v1/scans/slug/doesnotexist1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"
