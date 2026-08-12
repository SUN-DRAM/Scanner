"""Tests for the safety layer (contract §7.2, §10)."""

from __future__ import annotations

import ipaddress

import pytest

from app.errors import ApiException, ErrorCode
from app.safety import (
    PER_MODULE_TIMEOUT_SECONDS,
    RENEGOTIATION_PROBE_TIMEOUT_SECONDS,
    SCANNER_USER_AGENT,
    HostnameResolutionError,
    is_blocked_ip,
    is_denylisted_hostname,
    normalize_hostname,
    resolve_and_validate,
    validate_port,
)

# --- §7.2 hostname normalisation ---


def test_normalize_hostname_strips_scheme_case_path_and_query() -> None:
    result = normalize_hostname("https://Example.COM/path?q=1", None)
    assert result.hostname == "example.com"
    assert result.port == 443


def test_normalize_hostname_strips_http_scheme_too() -> None:
    result = normalize_hostname("HTTP://Example.com", None)
    assert result.hostname == "example.com"


def test_normalize_hostname_idn_converts_to_punycode() -> None:
    result = normalize_hostname("münchen.de", None)
    assert result.hostname == "xn--mnchen-3ya.de"


def test_normalize_hostname_strips_trailing_dot() -> None:
    result = normalize_hostname("example.com.", None)
    assert result.hostname == "example.com"


def test_normalize_hostname_uses_embedded_port_when_not_supplied() -> None:
    result = normalize_hostname("example.com:8443", None)
    assert result.hostname == "example.com"
    assert result.port == 8443


def test_normalize_hostname_supplied_port_wins_over_embedded_port() -> None:
    result = normalize_hostname("example.com:8443", 443)
    assert result.port == 443


def test_normalize_hostname_defaults_to_443_when_nothing_supplied() -> None:
    result = normalize_hostname("example.com", None)
    assert result.port == 443


def test_normalize_hostname_rejects_hostname_without_a_dot() -> None:
    with pytest.raises(ApiException) as exc_info:
        normalize_hostname("bare-hostname", None)
    assert exc_info.value.code == ErrorCode.INVALID_HOSTNAME


def test_normalize_hostname_rejects_empty_string() -> None:
    with pytest.raises(ApiException) as exc_info:
        normalize_hostname("   ", None)
    assert exc_info.value.code == ErrorCode.INVALID_HOSTNAME


def test_normalize_hostname_rejects_invalid_label_characters() -> None:
    with pytest.raises(ApiException) as exc_info:
        normalize_hostname("exa_mple!.com", None)
    assert exc_info.value.code == ErrorCode.INVALID_HOSTNAME


def test_normalize_hostname_rejects_label_over_63_chars() -> None:
    long_label = "a" * 64
    with pytest.raises(ApiException) as exc_info:
        normalize_hostname(f"{long_label}.com", None)
    assert exc_info.value.code == ErrorCode.INVALID_HOSTNAME


# --- §10 rule 3: port allowlist ---


def test_validate_port_allows_443_and_8443() -> None:
    validate_port(443)
    validate_port(8443)


def test_validate_port_rejects_22() -> None:
    with pytest.raises(ApiException) as exc_info:
        validate_port(22)
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


def test_validate_port_rejects_80_without_redirect_probe_flag() -> None:
    with pytest.raises(ApiException) as exc_info:
        validate_port(80)
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


def test_validate_port_allows_80_for_redirect_probe() -> None:
    validate_port(80, allow_redirect_probe_port_80=True)


# --- §10 rule 1: private/reserved range blocklist ---


@pytest.mark.parametrize(
    "ip",
    [
        "10.1.2.3",
        "172.16.0.5",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
def test_is_blocked_ip_rejects_private_and_reserved_ranges(ip: str) -> None:
    assert is_blocked_ip(ipaddress.ip_address(ip)) is True


def test_is_blocked_ip_allows_public_address() -> None:
    assert is_blocked_ip(ipaddress.ip_address("93.184.216.34")) is False


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_metadata_ip_literal() -> None:
    with pytest.raises(ApiException) as exc_info:
        await resolve_and_validate("169.254.169.254")
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_private_ip_literal() -> None:
    with pytest.raises(ApiException) as exc_info:
        await resolve_and_validate("10.0.0.5")
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_loopback_ip_literal() -> None:
    with pytest.raises(ApiException) as exc_info:
        await resolve_and_validate("127.0.0.1")
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_own_public_ip_literal() -> None:
    """Phase 2 Step 0.1: our own Elastic IP, submitted directly, is blocked."""
    with pytest.raises(ApiException) as exc_info:
        await resolve_and_validate("65.2.195.179")
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


# --- §10 rule 8: static host denylist ---


def test_is_denylisted_hostname_matches_localhost_variants() -> None:
    assert is_denylisted_hostname("localhost") is True
    assert is_denylisted_hostname("localhost.localdomain") is True
    assert is_denylisted_hostname("metadata.google.internal") is True


def test_is_denylisted_hostname_matches_subdomains_of_denylisted_hosts() -> None:
    assert is_denylisted_hostname("foo.localhost") is True


def test_is_denylisted_hostname_allows_ordinary_domain() -> None:
    assert is_denylisted_hostname("example.com") is False


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_denylisted_hostname() -> None:
    with pytest.raises(ApiException) as exc_info:
        await resolve_and_validate("localhost.localdomain")
    assert exc_info.value.code == ErrorCode.BLOCKED_TARGET


@pytest.mark.asyncio
async def test_resolve_and_validate_raises_resolution_error_for_bogus_tld() -> None:
    with pytest.raises(HostnameResolutionError):
        await resolve_and_validate("this-domain-should-not-exist-sundram.invalid")


# --- §10 rule 10: headers module User-Agent (Gate A follow-up A1) ---


def test_renegotiation_probe_timeout_is_well_under_the_module_budget() -> None:
    # Regression guard for the razorpay.com finding (Gate A follow-up A1): a
    # server that silently ignores a renegotiation request never answers it
    # at all, so pumping on it up to the *full* per-handshake budget wastes
    # nearly the whole thing on a probe whose answer is already "no" and
    # loses the race against run_module's own outer timeout. This probe must
    # stay a small fraction of the module budget, not share it.
    assert RENEGOTIATION_PROBE_TIMEOUT_SECONDS < PER_MODULE_TIMEOUT_SECONDS / 2


def test_scanner_user_agent_is_not_the_httpx_default() -> None:
    # Regression guard for the swiggy.com finding: an unmodified `python-httpx/*`
    # User-Agent gets an outright WAF block (403, no security headers at all)
    # on real production sites, which reads as a false MISSING on every header.
    # `httpx`'s own default is generated from its version, so "does not start
    # with python-httpx" is the stable, version-independent thing to assert.
    assert not SCANNER_USER_AGENT.startswith("python-httpx")
    assert "Mozilla" in SCANNER_USER_AGENT
