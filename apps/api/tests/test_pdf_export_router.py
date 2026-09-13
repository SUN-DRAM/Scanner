"""Router-level tests for `GET /api/v1/scans/{scan_id}/report.pdf` and
`GET /api/v1/scans/slug/{public_slug}/report.pdf` (contract §7.14, v2.9),
against a real Postgres + Redis — same pattern as test_scans_router.py.

Run via `docker compose exec api pytest` — `db_session`/`redis_client`
(tests/conftest.py) skip gracefully when those aren't reachable.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.enums import ScanStatus
from app.main import app
from app.models import ScanRecord
from app.redis_client import get_arq_pool, get_redis_client
from tests.conftest import FakeArqPool
from tests.pdf_fixtures import make_completed_scan, make_finding


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
    # Fresh synthetic IP per test — see test_scans_router.py's identical
    # fixture for why (the rate limiter's Redis buckets are real and
    # persistent, not reset between test runs).
    return f"203.0.113.{uuid.uuid4().int % 250}"


@pytest.fixture
async def client(_wired_app: None, client_ip: str) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app, client=(client_ip, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def _test_hostname() -> str:
    return f"test-{uuid.uuid4().hex}.example.com"


async def _insert_completed_scan(
    db_session: AsyncSession, *, hostname: str | None = None, findings: list | None = None
) -> ScanRecord:
    hostname = hostname or _test_hostname()
    scan = make_completed_scan(hostname=hostname, findings=findings or [])
    record = ScanRecord(
        scan_id=uuid.UUID(scan.scan_id),
        public_slug=scan.public_slug,
        hostname=hostname,
        port=443,
        status=ScanStatus.COMPLETED.value,
        overall_grade=scan.overall_grade,
        overall_score=scan.overall_score,
        headline=scan.headline,
        result=scan.model_dump(mode="json"),
        completed_at=scan.completed_at,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def _cleanup(db_session: AsyncSession, hostname: str) -> None:
    await db_session.execute(delete(ScanRecord).where(ScanRecord.hostname == hostname))
    await db_session.commit()


async def _clear_pdf_rate_limit(redis_client: Redis, client_ip: str) -> None:
    from app.ratelimit import hash_for_bucket

    await redis_client.delete(f"ratelimit:pdf:ip:{hash_for_bucket(client_ip)}")


@pytest.mark.usefixtures("require_weasyprint")
@pytest.mark.asyncio
async def test_completed_scan_returns_a_pdf_by_id(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    record = await _insert_completed_scan(db_session)
    try:
        response = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]
        assert record.hostname in response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF")
    finally:
        await _clear_pdf_rate_limit(redis_client, client_ip)
        await _cleanup(db_session, record.hostname)


@pytest.mark.usefixtures("require_weasyprint")
@pytest.mark.asyncio
async def test_completed_scan_returns_a_pdf_by_slug(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    record = await _insert_completed_scan(db_session)
    try:
        response = await client.get(f"/api/v1/scans/slug/{record.public_slug}/report.pdf")
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
    finally:
        await _clear_pdf_rate_limit(redis_client, client_ip)
        await _cleanup(db_session, record.hostname)


@pytest.mark.asyncio
async def test_returns_404_for_unknown_scan_id(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/scans/{uuid.uuid4()}/report.pdf")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_returns_404_for_unknown_slug(client: AsyncClient) -> None:
    response = await client.get("/api/v1/scans/slug/doesnotexist1/report.pdf")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCAN_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_value", [ScanStatus.QUEUED, ScanStatus.RUNNING])
async def test_returns_409_for_a_scan_that_is_not_yet_complete(
    client: AsyncClient, db_session: AsyncSession, status_value: ScanStatus
) -> None:
    hostname = _test_hostname()
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=status_value.value,
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    try:
        response = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "REPORT_NOT_AVAILABLE"
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_returns_409_for_a_failed_scan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Step 1.3's decision, unchanged: a failed scan has no grade, no
    # findings, no modules — a PDF of it would be an empty document with
    # our logo on it, so it gets no PDF at all, same as queued/running.
    hostname = _test_hostname()
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=ScanStatus.FAILED.value,
        error_code="SCAN_FAILED",
        error_message=f"'{hostname}' does not resolve.",
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    try:
        response = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "REPORT_NOT_AVAILABLE"
    finally:
        await _cleanup(db_session, hostname)


@pytest.mark.asyncio
async def test_no_rescan_is_triggered(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    """A PDF request must never create a new `scans` row or enqueue a job —
    it only ever reads one already written by the scan path."""
    record = await _insert_completed_scan(db_session)
    try:
        count_stmt = select(func.count()).select_from(ScanRecord)
        before = (await db_session.execute(count_stmt)).scalar_one()
        with patch("app.routers.scans.render_scan_pdf", new=AsyncMock(return_value=b"%PDF-fake")):
            response = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
        assert response.status_code == 200
        after = (await db_session.execute(count_stmt)).scalar_one()
        assert after == before
    finally:
        await _clear_pdf_rate_limit(redis_client, client_ip)
        await _cleanup(db_session, record.hostname)


@pytest.mark.asyncio
async def test_second_request_for_the_same_scan_is_served_from_cache(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    record = await _insert_completed_scan(db_session)
    try:
        fake_render = AsyncMock(return_value=b"%PDF-fake-bytes")
        with patch("app.routers.scans.render_scan_pdf", new=fake_render):
            first = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
            second = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.content == second.content == b"%PDF-fake-bytes"
        # Only the first request should have actually rendered.
        assert fake_render.await_count == 1
    finally:
        await _clear_pdf_rate_limit(redis_client, client_ip)
        await _cleanup(db_session, record.hostname)


@pytest.mark.asyncio
async def test_rate_limit_trips_after_the_configured_ceiling(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    # RATE_LIMIT_PDF_PER_IP_PER_HOUR defaults to 10 (contract §4). Each
    # request uses a distinct scan_id so every one is a cache miss and
    # actually consumes the per-IP budget — a cache hit deliberately bypasses
    # the limiter (same precedent as POST /scans's cached-scan path).
    hostnames: list[str] = []
    fake_render = AsyncMock(return_value=b"%PDF-fake-bytes")
    try:
        with patch("app.routers.scans.render_scan_pdf", new=fake_render):
            for _ in range(10):
                record = await _insert_completed_scan(db_session)
                hostnames.append(record.hostname)
                ok = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
                assert ok.status_code == 200

            overflow_record = await _insert_completed_scan(db_session)
            hostnames.append(overflow_record.hostname)
            limited = await client.get(f"/api/v1/scans/{overflow_record.scan_id}/report.pdf")

        assert limited.status_code == 429
        body = limited.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert body["error"]["details"]["retry_after_seconds"] > 0
    finally:
        await _clear_pdf_rate_limit(redis_client, client_ip)
        for hostname in hostnames:
            await _cleanup(db_session, hostname)


@pytest.mark.usefixtures("require_weasyprint")
@pytest.mark.asyncio
async def test_pdf_content_matches_the_scan_it_was_generated_from(
    client: AsyncClient, db_session: AsyncSession, redis_client: Redis, client_ip: str
) -> None:
    from pypdf import PdfReader

    findings = [make_finding(code="CERT_EXPIRING_SOON", severity="high")]
    record = await _insert_completed_scan(db_session, findings=findings)
    try:
        scan_response = await client.get(f"/api/v1/scans/{record.scan_id}")
        scan_body = scan_response.json()

        pdf_response = await client.get(f"/api/v1/scans/{record.scan_id}/report.pdf")
        assert pdf_response.status_code == 200
        reader = PdfReader(io.BytesIO(pdf_response.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        assert scan_body["overall_grade"] in text
        assert str(scan_body["overall_score"]) in text
        for finding in scan_body["findings"]:
            assert finding["title"] in text
    finally:
        await _clear_pdf_rate_limit(redis_client, client_ip)
        await _cleanup(db_session, record.hostname)
