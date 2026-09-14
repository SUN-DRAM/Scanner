"""Live integration tests for the `chain` module."""

from __future__ import annotations

import asyncio
import ssl
import time
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.enums import ModuleStatus
from app.safety import (
    CONNECTION_CLOSE_TIMEOUT_SECONDS,
    open_pinned_connection,
    resolve_and_validate,
)
from app.scanner import ScanContext
from app.scanner import chain as chain_module
from app.scanner.chain import run


def _ctx(hostname: str, port: int = 443) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_google_com_has_a_complete_trusted_chain(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    assert result.data.chain_length >= 2
    assert result.data.is_complete is True
    assert result.data.trusted_root is not None
    assert not any(f.code == "CHAIN_UNTRUSTED_ROOT" for f in result.findings)


@pytest.mark.asyncio
async def test_self_signed_badssl_chain_is_untrusted(require_internet: None) -> None:
    result = await run(_ctx("self-signed.badssl.com"))
    assert result.status == ModuleStatus.FAIL
    assert result.data is not None
    assert result.data.trusted_root is None
    assert any(f.code == "CHAIN_UNTRUSTED_ROOT" for f in result.findings)


@pytest.mark.asyncio
async def test_untrusted_root_badssl_chain_is_untrusted(require_internet: None) -> None:
    result = await run(_ctx("untrusted-root.badssl.com"))
    assert result.status == ModuleStatus.FAIL
    assert any(f.code == "CHAIN_UNTRUSTED_ROOT" for f in result.findings)


@pytest.mark.asyncio
async def test_incomplete_chain_badssl_reports_incomplete(require_internet: None) -> None:
    result = await run(_ctx("incomplete-chain.badssl.com"))
    assert result.data is not None
    assert result.data.chain_length == 1
    assert result.data.is_complete is False
    assert any(f.code == "CHAIN_INCOMPLETE" for f in result.findings)


@pytest.mark.asyncio
async def test_certificate_roles_are_classified(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    roles = [c.role for c in result.data.certificates]
    assert roles[0] == "leaf"
    assert all(role in ("leaf", "intermediate", "root") for role in roles)


@pytest.mark.asyncio
async def test_validates_against_trust_store_bounds_a_hanging_close(
    require_internet: None,
) -> None:
    """docs/fix_connection_footprint.md: a peer that never acknowledges the
    TLS/TCP close must not be able to hang this past its own short cap —
    confirmed by actually making writer.wait_closed() hang and asserting
    the call still returns promptly, not by reading the code."""
    real_open_pinned_connection = open_pinned_connection

    async def _open_with_hanging_close(
        ip: str,
        port: int,
        *,
        server_hostname: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = 8.0,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await real_open_pinned_connection(
            ip, port, server_hostname=server_hostname, ssl_context=ssl_context, timeout=timeout
        )

        async def _hang() -> None:
            await asyncio.Event().wait()

        writer.wait_closed = _hang  # type: ignore[method-assign]
        return reader, writer

    target = await resolve_and_validate("google.com")

    with patch("app.scanner.chain.open_pinned_connection", new=_open_with_hanging_close):
        started = time.monotonic()
        trusted = await chain_module._validates_against_trust_store(target.ip, 443, "google.com")
        elapsed = time.monotonic() - started

    assert trusted is True
    assert elapsed < CONNECTION_CLOSE_TIMEOUT_SECONDS + 2
