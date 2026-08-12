"""Tests for the error envelope (contract §7.4) and its exception handlers.

Two tiers, deliberately: the closed set of 8 error codes is walked entirely
offline against the shared `_envelope()` builder every handler funnels
through — that's the part that must never regress, and it must never need a
live network or database to prove it. A second, smaller tier exercises a
few of those codes through real HTTP requests (DB/Redis-gated, same pattern
as every other router test in this suite) to prove the wiring, not just the
primitive, is correct — including the specific regression this file exists
for: a `field_validator` that raises a plain `ValueError` used to produce an
unhandled 500 instead of a clean 422, because `ctx.error` held the raw
exception object and nothing in the response pipeline could serialize it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.enums import ScanStatus
from app.errors import ErrorCode, ErrorEnvelope, _envelope, _json_safe, _sanitize_validation_errors
from app.main import app
from app.models import ScanRecord

ALL_ERROR_CODES: tuple[ErrorCode, ...] = (
    ErrorCode.VALIDATION_ERROR,
    ErrorCode.INVALID_HOSTNAME,
    ErrorCode.BLOCKED_TARGET,
    ErrorCode.RATE_LIMITED,
    ErrorCode.SCAN_NOT_FOUND,
    ErrorCode.SCAN_FAILED,
    ErrorCode.UPSTREAM_TIMEOUT,
    ErrorCode.INTERNAL_ERROR,
)


def test_all_error_codes_constant_matches_the_closed_set() -> None:
    # Contract §7.4's table has exactly these 8 rows — if a code is ever
    # added or removed there, this constant (and the parametrized test
    # below) must be updated in the same session.
    assert set(ALL_ERROR_CODES) == set(ErrorCode)
    assert len(ALL_ERROR_CODES) == 8


@pytest.mark.parametrize("code", ALL_ERROR_CODES)
def test_every_error_code_produces_a_strictly_shaped_json_safe_envelope(code: ErrorCode) -> None:
    envelope = _envelope(
        code, "a human-readable message", {"some_key": "some_value", "n": 1}, "req_test1234"
    )

    # Exactly the shape contract §7.4 documents — no extra top-level keys,
    # nothing missing.
    assert set(envelope.keys()) == {"error"}
    assert set(envelope["error"].keys()) == {"code", "message", "details", "request_id"}
    assert envelope["error"]["code"] == code.value
    assert envelope["error"]["request_id"] == "req_test1234"

    # Re-parses as the same model — this is a schema check, not just a
    # serialization check.
    ErrorEnvelope.model_validate(envelope)

    # The actual bar this file exists to hold: json.dumps must never raise,
    # for any code in the closed set.
    round_tripped = json.loads(json.dumps(envelope))
    assert round_tripped == envelope


def test_envelope_with_null_details_is_json_safe() -> None:
    envelope = _envelope(ErrorCode.SCAN_NOT_FOUND, "not found", None, "req_test")
    assert envelope["error"]["details"] is None
    json.dumps(envelope)  # does not raise


# --- _json_safe / _sanitize_validation_errors: the ctx-filtering fix itself ---


def test_json_safe_keeps_plain_scalars() -> None:
    is_safe, value = _json_safe({"ge": 0, "limit_value": 10, "note": "ok", "flag": True})
    assert is_safe is True
    assert value == {"ge": 0, "limit_value": 10, "note": "ok", "flag": True}


def test_json_safe_drops_a_raw_exception_leaf_but_keeps_its_siblings() -> None:
    ctx = {"error": ValueError("must be non-negative"), "limit_value": 10}
    is_safe, value = _json_safe(ctx)
    assert is_safe is True  # the dict itself is representable...
    assert value == {"limit_value": 10}  # ...once the unsafe leaf is filtered out
    json.dumps(value)  # does not raise


def test_json_safe_recurses_into_nested_lists_and_dicts() -> None:
    ctx = {"nested": {"inner": [1, "two", 3.0, None], "bad": object()}}
    is_safe, value = _json_safe(ctx)
    assert is_safe is True
    assert value == {"nested": {"inner": [1, "two", 3.0, None]}}
    json.dumps(value)  # does not raise


def test_sanitize_validation_errors_preserves_json_safe_ctx() -> None:
    errors = [
        {
            "type": "greater_than_equal",
            "loc": ("x",),
            "msg": "Input should be greater than or equal to 0",
            "input": -1,
            "ctx": {"ge": 0},
            "url": "https://errors.pydantic.dev/2.11/v/greater_than_equal",
        }
    ]
    sanitized = _sanitize_validation_errors(errors)
    assert sanitized[0]["ctx"] == {"ge": 0}
    json.dumps(sanitized)  # does not raise


def test_sanitize_validation_errors_drops_ctx_key_entirely_when_nothing_survives() -> None:
    # A field_validator raising a plain ValueError — the documented Pydantic
    # pattern this app's own WaitlistCreateRequest.email validator uses —
    # produces exactly this shape. Before this fix, the whole `ctx` key was
    # dropped unconditionally; now it's dropped only because nothing inside
    # it happens to be JSON-safe, not as a blanket rule.
    errors = [
        {
            "type": "value_error",
            "loc": ("email",),
            "msg": "Value error, Not a valid email address.",
            "input": "not-an-email",
            "ctx": {"error": ValueError("Not a valid email address.")},
            "url": "https://errors.pydantic.dev/2.11/v/value_error",
        }
    ]
    sanitized = _sanitize_validation_errors(errors)
    assert "ctx" not in sanitized[0]
    assert sanitized[0]["msg"] == "Value error, Not a valid email address."
    json.dumps(sanitized)  # does not raise


def test_sanitize_validation_errors_handles_errors_with_no_ctx_key() -> None:
    errors = [{"type": "missing", "loc": ("hostname",), "msg": "Field required", "input": {}}]
    sanitized = _sanitize_validation_errors(errors)
    assert "ctx" not in sanitized[0]
    json.dumps(sanitized)  # does not raise


# --- end-to-end: a few of the 8 codes through real HTTP requests ---
# DB/Redis-gated (db_session, redis_client from conftest.py), same pattern as
# every other router test file — skips gracefully outside `docker compose
# exec api pytest`. Trigger-condition coverage (rate-limit thresholds,
# private-IP targets, etc.) already lives in test_scans_router.py /
# test_ratelimit.py / test_waitlist_router.py; this only re-verifies that the
# real response for each is envelope-shaped and JSON-safe, and specifically
# regression-guards the ctx.error crash for VALIDATION_ERROR.


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


async def _assert_envelope_shaped(response: httpx.Response, expected_code: str) -> None:
    body = response.json()
    ErrorEnvelope.model_validate(body)
    assert body["error"]["code"] == expected_code
    assert "request_id" in body["error"]
    json.dumps(body)  # does not raise


@pytest.mark.asyncio
async def test_validation_error_from_a_field_validator_value_error_is_a_clean_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The exact regression this file guards: WaitlistCreateRequest.email's
    # field_validator raises a plain ValueError on a malformed address.
    # Before the fix, ctx.error (the raw ValueError) reaching JSONResponse
    # would have turned this 422 into an unhandled 500.
    record = ScanRecord(
        scan_id=uuid.uuid4(),
        public_slug=uuid.uuid4().hex[:12],
        hostname="errors-test.example.com",
        port=443,
        status=ScanStatus.COMPLETED.value,
        result=None,
        client_ip_hash="deadbeef",
    )
    db_session.add(record)
    await db_session.commit()

    response = await client.post(
        "/api/v1/waitlist", json={"scan_id": str(record.scan_id), "email": "not-an-email"}
    )
    assert response.status_code == 422
    await _assert_envelope_shaped(response, "VALIDATION_ERROR")

    errors = response.json()["error"]["details"]["errors"]
    assert len(errors) >= 1
    for error in errors:
        if "ctx" in error:
            json.dumps(error["ctx"])  # whatever survived is JSON-safe


@pytest.mark.asyncio
async def test_invalid_hostname_end_to_end(client: AsyncClient) -> None:
    response = await client.post("/api/v1/scans", json={"hostname": "not a hostname"})
    assert response.status_code == 400
    await _assert_envelope_shaped(response, "INVALID_HOSTNAME")


@pytest.mark.asyncio
async def test_blocked_target_end_to_end(client: AsyncClient) -> None:
    response = await client.post("/api/v1/scans", json={"hostname": "example.com", "port": 22})
    assert response.status_code == 400
    await _assert_envelope_shaped(response, "BLOCKED_TARGET")


@pytest.mark.asyncio
async def test_scan_not_found_end_to_end(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/scans/{uuid.uuid4()}")
    assert response.status_code == 404
    await _assert_envelope_shaped(response, "SCAN_NOT_FOUND")
