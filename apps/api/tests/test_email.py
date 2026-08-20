"""Unit tests for app/notify/email.py (Gate D). Every router test overrides
get_email_sender with a fake, so ResendEmailSender's actual HTTP behaviour —
the real send, a 4xx from the provider, a network failure — has no coverage
anywhere else. Uses httpx.MockTransport, not a new mocking dependency, in
keeping with email.py's own "no SDK dependency added for a single POST".
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.config import Settings
from app.notify.email import (
    ConsoleEmailSender,
    EmailSendError,
    ResendEmailSender,
    get_email_sender,
)


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client = httpx.AsyncClient

    def _fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), timeout=10.0)

    monkeypatch.setattr("app.notify.email.httpx.AsyncClient", _fake_client)


@pytest.mark.asyncio
async def test_resend_email_sender_success_sends_expected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "test-email-id"})

    _patch_transport(monkeypatch, handler)

    sender = ResendEmailSender("re_test_key", "alerts@sundram.tech")
    await sender.send(to="user@example.com", subject="Hello", text="Body text")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test_key"


@pytest.mark.asyncio
async def test_resend_email_sender_sends_correct_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "test-email-id"})

    _patch_transport(monkeypatch, handler)

    sender = ResendEmailSender("re_test_key", "alerts@sundram.tech")
    await sender.send(to="user@example.com", subject="Hello", text="Body text")

    assert seen_payload == {
        "from": "alerts@sundram.tech",
        "to": ["user@example.com"],
        "subject": "Hello",
        "text": "Body text",
    }


@pytest.mark.asyncio
async def test_resend_email_sender_4xx_raises_without_leaking_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Resend echoes the request back on some 4xx errors — the response
        # body must never end up in the raised exception's message.
        return httpx.Response(422, json={"to": "user@example.com", "text": "Body text"})

    _patch_transport(monkeypatch, handler)

    sender = ResendEmailSender("re_test_key", "alerts@sundram.tech")
    with pytest.raises(EmailSendError) as exc_info:
        await sender.send(to="user@example.com", subject="Hello", text="Body text")

    message = str(exc_info.value)
    assert "422" in message
    assert "user@example.com" not in message
    assert "Body text" not in message


@pytest.mark.asyncio
async def test_resend_email_sender_network_error_raises_email_send_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_transport(monkeypatch, handler)

    sender = ResendEmailSender("re_test_key", "alerts@sundram.tech")
    with pytest.raises(EmailSendError):
        await sender.send(to="user@example.com", subject="Hello", text="Body text")


@pytest.mark.asyncio
async def test_console_email_sender_logs_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO, logger="app.notify.email"):
        await sender.send(to="user@example.com", subject="Hello", text="Body text")

    assert any(
        record.message == "email_not_sent_no_provider_configured" for record in caplog.records
    )


def _settings(**overrides: str) -> Settings:
    base = {"SESSION_SECRET": "test-secret", "CORS_ORIGINS": "http://test"}
    base.update(overrides)
    return Settings(**base)


def test_get_email_sender_picks_resend_when_both_vars_set() -> None:
    settings = _settings(RESEND_API_KEY="re_key", EMAIL_FROM_ADDRESS="alerts@sundram.tech")
    assert isinstance(get_email_sender(settings), ResendEmailSender)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"RESEND_API_KEY": "re_key"},
        {"EMAIL_FROM_ADDRESS": "alerts@sundram.tech"},
    ],
)
def test_get_email_sender_falls_back_to_console_when_either_var_is_missing(
    overrides: dict[str, str],
) -> None:
    settings = _settings(**overrides)
    assert isinstance(get_email_sender(settings), ConsoleEmailSender)
