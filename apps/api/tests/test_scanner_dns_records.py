"""Live integration tests for the `dns` module, including the WHOIS
null-safety rule from contract §7's rule 7 (never a wrong date)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scanner import ScanContext
from app.scanner.dns_records import _normalize_whois_date, run


def _ctx(hostname: str, port: int = 443) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_cloudflare_com_has_dnssec_and_caa(require_internet: None) -> None:
    result = await run(_ctx("cloudflare.com"))
    assert result.data is not None
    assert result.data.dnssec_enabled is True
    assert result.data.caa_present is True
    assert not any(f.code == "DNS_NO_DNSSEC" for f in result.findings)
    assert not any(f.code == "DNS_NO_CAA" for f in result.findings)


@pytest.mark.asyncio
async def test_google_com_resolves_a_records(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    assert len(result.data.a_records) > 0
    assert len(result.data.nameservers) > 0


@pytest.mark.asyncio
async def test_nonexistent_domain_returns_empty_lists_not_a_crash(require_internet: None) -> None:
    result = await run(_ctx("this-domain-should-not-exist-sundram.invalid"))
    assert result.data is not None
    assert result.data.a_records == []
    assert result.data.registrar is None
    assert result.data.domain_expires_at is None
    assert result.data.days_until_domain_expiry is None
    assert not any(f.code.startswith("DOMAIN_EXPIRING") for f in result.findings)


def test_normalize_whois_date_returns_none_for_contradictory_dates() -> None:
    contradictory = [
        datetime(2028, 9, 14, tzinfo=UTC),
        datetime(2028, 9, 13, tzinfo=UTC),
    ]
    assert _normalize_whois_date(contradictory) is None


def test_normalize_whois_date_accepts_agreeing_dates_with_different_times() -> None:
    agreeing = [
        datetime(2028, 9, 14, 4, 0, tzinfo=UTC),
        datetime(2028, 9, 14, 7, 0, tzinfo=UTC),
    ]
    result = _normalize_whois_date(agreeing)
    assert result is not None
    assert result.date() == agreeing[0].date()


def test_normalize_whois_date_returns_none_for_missing_value() -> None:
    assert _normalize_whois_date(None) is None
    assert _normalize_whois_date("not a date") is None
    assert _normalize_whois_date([]) is None
