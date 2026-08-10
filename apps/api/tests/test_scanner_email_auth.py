"""Live integration tests for the `email_auth` module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scanner import ScanContext
from app.scanner.email_auth import run


def _ctx(hostname: str, port: int = 443) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_google_com_has_spf_and_dmarc(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    assert result.data.spf.present is True
    assert result.data.spf.record is not None
    assert "v=spf1" in result.data.spf.record.lower()
    assert result.data.dmarc.present is True
    assert not any(f.code == "SPF_MISSING" for f in result.findings)
    assert not any(f.code == "DMARC_MISSING" for f in result.findings)


@pytest.mark.asyncio
async def test_github_com_spf_lookup_count_is_recursively_counted(require_internet: None) -> None:
    result = await run(_ctx("github.com"))
    assert result.data is not None
    assert result.data.spf.present is True
    # github.com's real SPF chain has multiple includes; a naive top-level-only
    # count would undercount this significantly below the true total.
    assert result.data.spf.lookup_count >= 5


@pytest.mark.asyncio
async def test_dkim_not_found_is_never_a_fail(require_internet: None) -> None:
    result = await run(_ctx("this-domain-should-not-exist-sundram.invalid"))
    dkim_findings = [f for f in result.findings if f.code == "DKIM_NOT_FOUND"]
    assert len(dkim_findings) == 1
    assert dkim_findings[0].severity == "info"
