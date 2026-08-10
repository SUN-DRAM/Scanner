"""Live integration tests for the `tls` module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scanner import ScanContext
from app.scanner.tls import run


def _ctx(hostname: str, port: int = 443) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_google_com_supports_tls13(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    assert result.data.protocols.tls1_3.supported is True
    assert result.data.protocols.tls1_3.deprecated is False
    assert result.data.protocols.tls1_0.deprecated is True
    assert not any(f.code == "TLS_NO_TLS13" for f in result.findings)


@pytest.mark.asyncio
async def test_tls_v1_1_only_badssl_reports_legacy_protocol(require_internet: None) -> None:
    result = await run(_ctx("tls-v1-1.badssl.com", 1011))
    assert result.data is not None
    assert result.data.protocols.tls1_1.supported is True
    assert any(f.code == "TLS_LEGACY_PROTOCOL" for f in result.findings)
    assert any(f.code == "TLS_NO_TLS13" for f in result.findings)


@pytest.mark.asyncio
async def test_forward_secrecy_detected_for_modern_negotiation(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    assert result.data.forward_secrecy is True
    assert not any(f.code == "TLS_NO_FORWARD_SECRECY" for f in result.findings)
