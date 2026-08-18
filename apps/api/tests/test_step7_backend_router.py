"""HTTP-level tests for the Phase 2 Step 7 backend additions (contract
§7.12 + the alert-preference fields on §7.7's `PATCH /orgs/current`):
recipient CRUD, RBAC (member read-only, owner/admin write), the monitor
alert log, and org alert-preference updates.
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
from app.main import app
from app.notify.email import get_email_sender
from app.ratelimit import hash_for_bucket
from app.redis_client import get_redis_client

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


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def _wired_app(
    db_session: AsyncSession, fake_email_sender: FakeEmailSender, redis_client: Redis
) -> Iterator[None]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_settings] = _test_settings
    app.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def _reset_otp_ip_rate_limit(redis_client: Redis) -> AsyncGenerator[None]:
    yield
    await redis_client.delete(f"ratelimit:otp:ip:{hash_for_bucket('127.0.0.1')}")


def _random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


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


async def _invite_and_login(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender, role: str
) -> AsyncClient:
    email = _random_email()
    await owner_client.post("/api/v1/orgs/current/members", json={"email": email, "role": role})
    client = await _new_client(_wired_app)
    await _login(client, fake_email_sender, email)
    return client


# --- PATCH /orgs/current alert preferences ---


@pytest.mark.asyncio
async def test_patch_org_applies_only_the_fields_sent(owner_client: AsyncClient) -> None:
    before = (await owner_client.get("/api/v1/orgs/current")).json()

    response = await owner_client.patch(
        "/api/v1/orgs/current", json={"quiet_hours_start": "22:00", "digest_hour": 7}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quiet_hours_start"] == "22:00"
    assert body["digest_hour"] == 7
    # Untouched fields keep their previous values.
    assert body["name"] == before["name"]
    assert body["quiet_hours_end"] == before["quiet_hours_end"]
    assert body["digest_mode"] == before["digest_mode"]


@pytest.mark.asyncio
async def test_patch_org_rejects_a_malformed_quiet_hour(owner_client: AsyncClient) -> None:
    response = await owner_client.patch("/api/v1/orgs/current", json={"quiet_hours_start": "9pm"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_org_rejects_an_unknown_timezone(owner_client: AsyncClient) -> None:
    response = await owner_client.patch("/api/v1/orgs/current", json={"timezone": "Mars/Olympus"})
    assert response.status_code == 422


# --- /alerts/recipients ---


@pytest.mark.asyncio
async def test_owner_can_create_list_and_delete_a_recipient(owner_client: AsyncClient) -> None:
    create_response = await owner_client.post(
        "/api/v1/alerts/recipients", json={"email": "ops@example.com", "monitor_id": None}
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["email"] == "ops@example.com"
    assert body["monitor_id"] is None
    assert body["verified"] is True

    list_response = await owner_client.get("/api/v1/alerts/recipients")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    delete_response = await owner_client.delete(f"/api/v1/alerts/recipients/{body['recipient_id']}")
    assert delete_response.status_code == 204

    list_again = await owner_client.get("/api/v1/alerts/recipients")
    assert list_again.json()["total"] == 0


@pytest.mark.asyncio
async def test_creating_the_same_recipient_twice_is_idempotent(owner_client: AsyncClient) -> None:
    first = await owner_client.post(
        "/api/v1/alerts/recipients", json={"email": "ops@example.com"}
    )
    assert first.status_code == 201

    second = await owner_client.post(
        "/api/v1/alerts/recipients", json={"email": "OPS@example.com"}  # case-insensitive
    )
    assert second.status_code == 200
    assert second.json()["recipient_id"] == first.json()["recipient_id"]

    total = (await owner_client.get("/api/v1/alerts/recipients")).json()["total"]
    assert total == 1


@pytest.mark.asyncio
async def test_member_can_read_but_not_write_recipients(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> None:
    member_client = await _invite_and_login(owner_client, _wired_app, fake_email_sender, "member")
    try:
        read_response = await member_client.get("/api/v1/alerts/recipients")
        assert read_response.status_code == 200

        write_response = await member_client.post(
            "/api/v1/alerts/recipients", json={"email": "hacker@example.com"}
        )
        assert write_response.status_code == 403
        assert write_response.json()["error"]["code"] == "FORBIDDEN"
    finally:
        await member_client.aclose()


@pytest.mark.asyncio
async def test_admin_can_manage_recipients(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> None:
    admin_client = await _invite_and_login(owner_client, _wired_app, fake_email_sender, "admin")
    try:
        response = await admin_client.post(
            "/api/v1/alerts/recipients", json={"email": "admin-added@example.com"}
        )
        assert response.status_code == 201
    finally:
        await admin_client.aclose()


@pytest.mark.asyncio
async def test_a_cross_org_recipient_id_returns_404_not_403(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> None:
    other_owner_client = await _new_client(_wired_app)
    try:
        await _login(other_owner_client, fake_email_sender, _random_email())
        other_recipient = await other_owner_client.post(
            "/api/v1/alerts/recipients", json={"email": "other-org@example.com"}
        )
        other_id = other_recipient.json()["recipient_id"]

        response = await owner_client.delete(f"/api/v1/alerts/recipients/{other_id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await other_owner_client.aclose()


# --- GET /monitors/{monitor_id}/alerts ---


@pytest.mark.asyncio
async def test_monitor_alert_log_is_empty_for_a_fresh_monitor(owner_client: AsyncClient) -> None:
    create_response = await owner_client.post(
        "/api/v1/monitors", json={"hostname": "example.com"}
    )
    assert create_response.status_code == 201
    monitor_id = create_response.json()["monitor_id"]

    response = await owner_client.get(f"/api/v1/monitors/{monitor_id}/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_monitor_alert_log_cross_org_id_is_404(
    owner_client: AsyncClient, _wired_app: None, fake_email_sender: FakeEmailSender
) -> None:
    other_owner_client = await _new_client(_wired_app)
    try:
        await _login(other_owner_client, fake_email_sender, _random_email())
        other_monitor = await other_owner_client.post(
            "/api/v1/monitors", json={"hostname": "other-example.com"}
        )
        other_monitor_id = other_monitor.json()["monitor_id"]

        response = await owner_client.get(f"/api/v1/monitors/{other_monitor_id}/alerts")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await other_owner_client.aclose()
