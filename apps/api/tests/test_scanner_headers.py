"""Live integration tests for the `headers` module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scanner import ScanContext
from app.scanner.headers import run


def _ctx(hostname: str, port: int = 443) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_github_com_redirects_http_to_https_with_hsts(require_internet: None) -> None:
    result = await run(_ctx("github.com"))
    assert result.data is not None
    assert result.data.http_to_https_redirect is True
    assert result.data.hsts.present is True
    assert result.data.final_url.startswith("https://")
    assert not any(f.code == "NO_HTTPS_REDIRECT" for f in result.findings)
    assert not any(f.code == "HSTS_MISSING" for f in result.findings)


@pytest.mark.asyncio
async def test_headers_still_readable_on_a_broken_certificate(require_internet: None) -> None:
    # A cert problem is certificate.py's/chain.py's concern — headers.py must
    # still be able to read the response, not cascade into its own failure.
    result = await run(_ctx("self-signed.badssl.com"))
    assert result.data is not None
    assert result.data.status_code == 200
    assert result.error is None


@pytest.mark.asyncio
async def test_missing_list_matches_presence_fields(require_internet: None) -> None:
    result = await run(_ctx("google.com"))
    assert result.data is not None
    d = result.data
    presence_by_field = {
        "hsts": d.hsts.present,
        "content_security_policy": d.content_security_policy.present,
        "x_content_type_options": d.x_content_type_options.present,
        "x_frame_options": d.x_frame_options.present,
        "referrer_policy": d.referrer_policy.present,
        "permissions_policy": d.permissions_policy.present,
    }
    expected_missing = {name for name, present in presence_by_field.items() if not present}
    assert set(d.missing) == expected_missing


# --- Gate A follow-up A1: hostname-crossing redirects (CONTRACT.md §6.4 v1.2) ---


@pytest.mark.asyncio
async def test_swiggy_com_headers_are_read_from_the_final_hop(require_internet: None) -> None:
    # swiggy.com's HTTP probe redirects apex -> https://www.swiggy.com — a
    # different hostname. Ground-truthed against curl: the real origin sets
    # HSTS on that final hop. With the httpx-default User-Agent, CloudFront's
    # WAF returned a bare 403 with no security headers at all, which the
    # module reported as a confident (and false) HSTS_MISSING. This is the
    # exact bug docs/GATE_A_FOLLOWUPS.md A1 asked to close.
    result = await run(_ctx("swiggy.com"))
    assert result.data is not None
    d = result.data
    assert d.final_url.startswith("https://www.swiggy.com")
    assert d.http_to_https_redirect is True
    assert d.hsts.present is True
    assert not any(f.code == "HSTS_MISSING" for f in result.findings)
    assert not any(f.code == "NO_HTTPS_REDIRECT" for f in result.findings)


@pytest.mark.asyncio
async def test_flipkart_com_reaches_the_real_origin_not_a_waf_challenge(
    require_internet: None,
) -> None:
    # flipkart.com's HTTP probe also crosses apex -> www. Ground-truthed
    # against curl from the deploy environment: the real origin returns 200
    # with a real Content-Security-Policy header naming flipkart/flixcart
    # domains. A WAF challenge page would come back as a non-200 with none of
    # the site's own headers.
    result = await run(_ctx("flipkart.com"))
    assert result.data is not None
    d = result.data
    assert d.final_url.startswith("https://www.flipkart.com")
    assert d.status_code == 200
    assert d.content_security_policy.present is True
    assert d.content_security_policy.value is not None
    assert "flipkart" in d.content_security_policy.value.lower()
