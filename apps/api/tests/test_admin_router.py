"""Tests for `GET /api/v1/admin/stats` (contract §7.5) — the token gate and
the basic shape of the plain-text table. Not part of the JSON API surface.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.enums import ScanStatus
from app.main import app
from app.models import ScanRecord


@pytest.fixture
def admin_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-admin-token-" + uuid.uuid4().hex
    monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()
    yield token
    get_settings.cache_clear()


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


@pytest.mark.asyncio
async def test_admin_stats_rejects_missing_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/stats")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_admin_stats_rejects_wrong_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/stats", params={"token": "wrong"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_stats_rejects_any_token_when_unconfigured(client: AsyncClient) -> None:
    # No `admin_token` fixture here — ADMIN_TOKEN defaults to empty, which
    # must refuse every request rather than accepting an empty match.
    response = await client.get("/api/v1/admin/stats", params={"token": ""})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_stats_returns_table_for_correct_token(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    hostname = f"test-{uuid.uuid4().hex}.example.com"
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=ScanStatus.COMPLETED.value,
        overall_grade="A+",
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()
    try:
        response = await client.get("/api/v1/admin/stats", params={"token": admin_token})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        body = response.text
        assert "Daily stats" in body
        assert "Last 100 scanned hostnames" in body
        assert hostname in body
    finally:
        await db_session.execute(delete(ScanRecord).where(ScanRecord.hostname == hostname))
        await db_session.commit()
