"""Live integration tests for the `certificate` module, against the exact
hosts the phase prompt's acceptance criteria name."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.enums import ModuleStatus
from app.scanner import ScanContext
from app.scanner.certificate import run


def _ctx(hostname: str, port: int = 443) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_google_com_is_a_healthy_certificate(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.status != ModuleStatus.ERROR
    assert result.data is not None
    assert result.data.is_expired is False
    assert result.data.is_self_signed is False
    assert result.data.hostname_matches is True
    assert not any(f.code == "CERT_EXPIRED" for f in result.findings)


@pytest.mark.asyncio
async def test_expired_badssl_reports_cert_expired(require_internet: None) -> None:
    result = await run(_ctx("expired.badssl.com"))
    assert result.status == ModuleStatus.FAIL
    assert result.data is not None
    assert result.data.is_expired is True
    assert result.grade == "F"
    assert any(f.code == "CERT_EXPIRED" for f in result.findings)


@pytest.mark.asyncio
async def test_self_signed_badssl_reports_self_signed(require_internet: None) -> None:
    result = await run(_ctx("self-signed.badssl.com"))
    assert result.status == ModuleStatus.FAIL
    assert result.data is not None
    assert result.data.is_self_signed is True
    assert any(f.code == "CERT_SELF_SIGNED" for f in result.findings)


@pytest.mark.asyncio
async def test_wrong_host_badssl_reports_hostname_mismatch(require_internet: None) -> None:
    result = await run(_ctx("wrong.host.badssl.com"))
    assert result.status == ModuleStatus.FAIL
    assert result.data is not None
    assert result.data.hostname_matches is False
    assert any(f.code == "CERT_HOSTNAME_MISMATCH" for f in result.findings)


@pytest.mark.asyncio
async def test_untrusted_root_badssl_leaf_is_otherwise_fine(require_internet: None) -> None:
    # untrusted-root.badssl.com's leaf certificate is valid for its hostname —
    # the untrusted root is chain.py's concern (CHAIN_UNTRUSTED_ROOT), not
    # certificate.py's. This module should not flag it as expired/mismatched.
    result = await run(_ctx("untrusted-root.badssl.com"))
    assert result.data is not None
    assert result.data.is_expired is False
    assert result.data.hostname_matches is True
    assert not any(f.code == "CERT_HOSTNAME_MISMATCH" for f in result.findings)


@pytest.mark.asyncio
async def test_nonexistent_domain_errors_without_crashing(require_internet: None) -> None:
    result = await run(_ctx("this-domain-should-not-exist-sundram.invalid"))
    assert result.status == ModuleStatus.ERROR
    assert result.data is None
    assert result.error is not None
    assert result.findings == []
