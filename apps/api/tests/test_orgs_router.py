"""HTTP-level tests for /api/v1/orgs/current* (contract §Step 2): role
enforcement and the cross-org-id-returns-404 rule from §7.6.
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
    # See test_auth_router.py's _wired_app: without this override, login
    # (which every fixture here does at least once) hits the process-wide
    # lru_cache'd Redis singleton bound to a stale event loop from a
    # previous test.
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def _reset_otp_ip_rate_limit(redis_client: Redis) -> AsyncGenerator[None]:
    # See test_auth_router.py's fixture of the same name: every test here
    # logs in at least once (owner_client), and ASGITransport reports every
    # in-process request as 127.0.0.1, so without this the shared per-IP OTP
    # rate limit bucket (10/hour, §7.6) eventually fails an unrelated test.
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


@pytest.mark.asyncio
async def test_owner_can_read_and_rename_their_org(owner_client: AsyncClient) -> None:
    get_response = await owner_client.get("/api/v1/orgs/current")
    assert get_response.status_code == 200
    org_id = get_response.json()["org_id"]

    patch_response = await owner_client.patch("/api/v1/orgs/current", json={"name": "Renamed Co"})
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Renamed Co"
    assert patch_response.json()["org_id"] == org_id


@pytest.mark.asyncio
async def test_member_gets_403_on_a_write(
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

    member_client = await _new_client(_wired_app)
    try:
        await _login(member_client, fake_email_sender, member_email)

        patch_response = await member_client.patch(
            "/api/v1/orgs/current", json={"name": "Hijacked"}
        )
        assert patch_response.status_code == 403
        assert patch_response.json()["error"]["code"] == "FORBIDDEN"

        invite_response = await member_client.post(
            "/api/v1/orgs/current/members", json={"email": _random_email(), "role": "member"}
        )
        assert invite_response.status_code == 403
    finally:
        await member_client.aclose()


@pytest.mark.asyncio
async def test_invited_member_is_attached_to_the_inviting_org_not_a_new_one(
    owner_client: AsyncClient,
    _wired_app: None,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    org_response = await owner_client.get("/api/v1/orgs/current")
    org_id = org_response.json()["org_id"]

    member_email = _random_email()
    await owner_client.post(
        "/api/v1/orgs/current/members", json={"email": member_email, "role": "member"}
    )

    member_client = await _new_client(_wired_app)
    try:
        await _login(member_client, fake_email_sender, member_email)
        member_org_response = await member_client.get("/api/v1/orgs/current")
        assert member_org_response.status_code == 200
        assert member_org_response.json()["org_id"] == org_id
    finally:
        await member_client.aclose()


@pytest.mark.asyncio
async def test_a_cross_org_member_id_returns_404_not_403(
    owner_client: AsyncClient,
    _wired_app: None,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    other_owner_client = await _new_client(_wired_app)
    try:
        other_owner = await _login(other_owner_client, fake_email_sender, _random_email())
        other_user_id = other_owner["user_id"]

        # owner_client's org has no idea this user_id belongs to a
        # different org entirely — it must not be able to tell the
        # difference between "not a member" and "a member of org B".
        response = await owner_client.delete(f"/api/v1/orgs/current/members/{other_user_id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await other_owner_client.aclose()


@pytest.mark.asyncio
async def test_last_owner_cannot_be_removed(owner_client: AsyncClient) -> None:
    me_response = await owner_client.get("/api/v1/auth/me")
    owner_user_id = me_response.json()["user_id"]

    response = await owner_client.delete(f"/api/v1/orgs/current/members/{owner_user_id}")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_owner_can_list_and_remove_a_member(
    owner_client: AsyncClient,
    _wired_app: None,
    fake_email_sender: FakeEmailSender,
    redis_client: Redis,
) -> None:
    member_email = _random_email()
    await owner_client.post(
        "/api/v1/orgs/current/members", json={"email": member_email, "role": "member"}
    )

    list_response = await owner_client.get("/api/v1/orgs/current/members")
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 2  # the owner plus the invited member
    emails = {item["email"] for item in body["items"]}
    assert member_email in emails

    member_id = next(
        item["user_id"] for item in body["items"] if item["email"] == member_email
    )
    delete_response = await owner_client.delete(f"/api/v1/orgs/current/members/{member_id}")
    assert delete_response.status_code == 204

    list_again = await owner_client.get("/api/v1/orgs/current/members")
    assert list_again.json()["total"] == 1
