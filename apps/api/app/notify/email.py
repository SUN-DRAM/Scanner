"""Email delivery, behind one interface so Phase 3 can add channels (§Step
5) without touching a call site. Built now, ahead of Step 5, because §7.6's
OTP flow (Step 2) already needs to actually send an email — see the
CONTRACT GAP note on `Settings.resend_api_key` in app/config.py.

`get_email_sender()` picks the implementation the same way `observability.py`
picks whether to initialise Sentry: an empty key means "not configured",
never a silent default that pretends to work.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx
from fastapi import Depends

from app.config import Settings, get_settings

logger = logging.getLogger("app.notify.email")

_RESEND_API_URL = "https://api.resend.com/emails"


class EmailSendError(Exception):
    """Raised when a configured sender fails to hand the email to the
    provider. Callers (app/otp.py, and later app/alerts/*) decide how to
    react — retry, log, or surface an error — this module only reports."""


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, text: str) -> None: ...


class ConsoleEmailSender:
    """Default when RESEND_API_KEY is unset — dev and the test suite never
    need a real provider account to exercise the OTP flow. Logs at INFO so
    a developer can read the code straight out of the container logs."""

    async def send(self, *, to: str, subject: str, text: str) -> None:
        logger.info(
            "email_not_sent_no_provider_configured",
            extra={"to": to, "subject": subject, "body": text},
        )


class ResendEmailSender:
    """Minimal Resend API client — just the one call this product needs.
    No SDK dependency added for a single POST."""

    def __init__(self, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from_address = from_address

    async def send(self, *, to: str, subject: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    _RESEND_API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "from": self._from_address,
                        "to": [to],
                        "subject": subject,
                        "text": text,
                    },
                )
            except httpx.HTTPError as exc:
                raise EmailSendError(f"Resend request failed: {exc}") from exc

        if response.status_code >= 400:
            # Never log response.text — Resend echoes the request back on
            # some 4xx errors, and that request body is the email itself.
            raise EmailSendError(f"Resend returned {response.status_code}")


def get_email_sender(settings: Settings = Depends(get_settings)) -> EmailSender:
    # Depends(get_settings), not a plain default: FastAPI treats an
    # un-annotated Pydantic-model parameter as a request body field, which
    # silently turned this route's request body into {"payload": ...,
    # "settings": ...} instead of the bare OtpRequestRequest shape.
    if settings.resend_api_key and settings.email_from_address:
        return ResendEmailSender(settings.resend_api_key, settings.email_from_address)
    return ConsoleEmailSender()
