"""Request/response shape tests for `POST /api/v1/waitlist` (contract §7.5),
against a real Postgres — same pattern as test_scans_router.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.enums import ScanStatus
from app.main import app
from app.models import DailyStatsRecord, ScanRecord, WaitlistSignupRecord


@pytest.fixture
def _wired_app(db_session: AsyncSession) -> Iterator[None]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(_wired_app: None) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def _test_hostname() -> str:
    return f"test-{uuid.uuid4().hex}.example.com"


async def _make_scan(db_session: AsyncSession, hostname: str) -> ScanRecord:
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=ScanStatus.COMPLETED.value,
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def _cleanup(db_session: AsyncSession, hostname: str, scan_id: uuid.UUID) -> None:
    await db_session.execute(
        delete(WaitlistSignupRecord).where(WaitlistSignupRecord.scan_id == scan_id)
    )
    await db_session.execute(delete(ScanRecord).where(ScanRecord.hostname == hostname))
    await db_session.commit()


@pytest.mark.asyncio
async def test_post_waitlist_stores_signup_and_confirms_hostname(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    scan = await _make_scan(db_session, hostname)
    try:
        response = await client.post(
            "/api/v1/waitlist", json={"scan_id": str(scan.scan_id), "email": "buyer@example.com"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["hostname"] == hostname
        assert body["message"] == f"We'll email you 30 days before {hostname} expires."

        stmt = select(WaitlistSignupRecord).where(WaitlistSignupRecord.scan_id == scan.scan_id)
        stored = (await db_session.execute(stmt)).scalar_one()
        assert stored.email == "buyer@example.com"
        assert stored.hostname == hostname
        assert stored.client_ip_hash is not None
    finally:
        await _cleanup(db_session, hostname, scan.scan_id)


@pytest.mark.asyncio
async def test_post_waitlist_derives_hostname_from_scan_not_the_request(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The request body has no hostname field at all — this asserts the
    # response can only ever reflect the scanned hostname, never a
    # client-supplied one, since there is nowhere for a client value to enter.
    hostname = _test_hostname()
    scan = await _make_scan(db_session, hostname)
    try:
        response = await client.post(
            "/api/v1/waitlist", json={"scan_id": str(scan.scan_id), "email": "buyer@example.com"}
        )
        assert response.json()["hostname"] == hostname
    finally:
        await _cleanup(db_session, hostname, scan.scan_id)


@pytest.mark.asyncio
async def test_post_waitlist_rejects_malformed_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    scan = await _make_scan(db_session, hostname)
    try:
        response = await client.post(
            "/api/v1/waitlist", json={"scan_id": str(scan.scan_id), "email": "not-an-email"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        await _cleanup(db_session, hostname, scan.scan_id)


@pytest.mark.asyncio
async def test_post_waitlist_returns_404_for_unknown_scan_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/waitlist", json={"scan_id": str(uuid.uuid4()), "email": "buyer@example.com"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_post_waitlist_returns_404_for_a_malformed_scan_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/waitlist", json={"scan_id": "not-a-uuid", "email": "buyer@example.com"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"


async def _waitlist_signup_count(db_session: AsyncSession, day: object) -> int:
    # A plain-column select rather than `session.get(DailyStatsRecord, ...)`:
    # it returns a scalar, not an ORM-tracked instance, so it never touches
    # the identity map and always re-reads the row — the increment happens
    # via a Core-level upsert (app/stats.py) on the same session, which
    # wouldn't otherwise be reflected in an already-loaded ORM object.
    stmt = select(DailyStatsRecord.waitlist_signups).where(DailyStatsRecord.day == day)
    result = await db_session.execute(stmt)
    return result.scalar_one_or_none() or 0


@pytest.mark.asyncio
async def test_post_waitlist_increments_daily_stats(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hostname = _test_hostname()
    scan = await _make_scan(db_session, hostname)
    today = datetime.now(UTC).date()
    try:
        before_count = await _waitlist_signup_count(db_session, today)

        response = await client.post(
            "/api/v1/waitlist", json={"scan_id": str(scan.scan_id), "email": "buyer@example.com"}
        )
        assert response.status_code == 200

        after_count = await _waitlist_signup_count(db_session, today)
        assert after_count == before_count + 1
    finally:
        await _cleanup(db_session, hostname, scan.scan_id)
