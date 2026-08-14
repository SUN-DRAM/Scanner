"""HTTP-level tests for /api/v1/auth/* (contract §7.6), against a real
Postgres and Redis — same pattern as test_waitlist_router.py.
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
    # Otherwise enforce_otp_request_rate_limits hits the process-wide
    # lru_cache'd Redis singleton (app/redis_client.py), which gets bound to
    # whatever event loop was running on first use — a different loop than
    # this test's, since pytest-asyncio gives each test function its own.
    # Same pattern test_scans_router.py already uses for the scan rate limit.
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def _reset_otp_ip_rate_limit(redis_client: Redis) -> AsyncGenerator[None]:
    # httpx's ASGITransport reports every in-process request as coming from
    # 127.0.0.1, so every test in this file shares one Redis bucket for the
    # per-IP OTP rate limit (10/hour, contract §7.6) — without this, tests
    # start failing with OTP_RATE_LIMITED once ~10 of them have run against
    # the same real Redis instance, in an order-dependent way that has
    # nothing to do with what each test is actually checking.
    yield
    await redis_client.delete(f"ratelimit:otp:ip:{hash_for_bucket('127.0.0.1')}")


@pytest.fixture
async def client(_wired_app: None) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def _random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


@pytest.mark.asyncio
async def test_get_me_without_a_session_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_otp_request_returns_identical_response_for_any_syntactically_valid_email(
    client: AsyncClient, redis_client: Redis
) -> None:
    for email in (_random_email(), _random_email()):
        response = await client.post("/api/v1/auth/otp/request", json={"email": email})
        assert response.status_code == 202
        assert response.json() == {"message": "If that email has an account, we've sent a code."}


@pytest.mark.asyncio
async def test_otp_request_rejects_malformed_email(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/otp/request", json={"email": "not-an-email"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_full_login_flow_sets_cookie_and_authenticates_subsequent_requests(
    client: AsyncClient, fake_email_sender: FakeEmailSender, redis_client: Redis
) -> None:
    email = _random_email()

    request_response = await client.post("/api/v1/auth/otp/request", json={"email": email})
    assert request_response.status_code == 202
    code = _extract_code(fake_email_sender)

    verify_response = await client.post(
        "/api/v1/auth/otp/verify", json={"email": email, "code": code}
    )
    assert verify_response.status_code == 200
    body = verify_response.json()
    assert body["email"] == email
    assert body["email_verified"] is True
    assert "sd_session" in verify_response.cookies

    me_response = await client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email


@pytest.mark.asyncio
async def test_verify_with_wrong_code_is_rejected(
    client: AsyncClient, redis_client: Redis
) -> None:
    email = _random_email()
    await client.post("/api/v1/auth/otp/request", json={"email": email})

    response = await client.post(
        "/api/v1/auth/otp/verify", json={"email": email, "code": "000000"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OTP_INVALID"


@pytest.mark.asyncio
async def test_logout_revokes_the_session(
    client: AsyncClient, fake_email_sender: FakeEmailSender, redis_client: Redis
) -> None:
    email = _random_email()
    await client.post("/api/v1/auth/otp/request", json={"email": email})
    code = _extract_code(fake_email_sender)
    await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})

    logout_response = await client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200

    me_response = await client.get("/api/v1/auth/me")
    assert me_response.status_code == 401
