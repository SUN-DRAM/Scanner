"""Live integration tests for the `chain` module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.enums import ModuleStatus
from app.scanner import ScanContext
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
