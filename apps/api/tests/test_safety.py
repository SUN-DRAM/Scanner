"""Tests for the safety layer (contract §7.2, §10)."""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import ssl
import time
from unittest.mock import patch

import httpx
import pytest
from OpenSSL import SSL as openssl_ssl

from app.enums import ModuleErrorCode
from app.errors import ApiException, ErrorCode
from app.safety import (
    CONNECTION_CLOSE_TIMEOUT_SECONDS,
    HTTP_REDIRECT_PROBE_TIMEOUT_SECONDS,
    PER_MODULE_TIMEOUT_SECONDS,
    RENEGOTIATION_PROBE_TIMEOUT_SECONDS,
    SCANNER_USER_AGENT,
    HostnameResolutionError,
    classify_module_exception,
    is_blocked_ip,
    is_denylisted_hostname,
    normalize_hostname,
    resolve_and_validate,
    safe_get,
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


def test_normalize_hostname_error_truncates_a_pathologically_long_input() -> None:
    # A 300-char pasted string must not come back verbatim in the error —
    # that blew out the report page's layout in production (Gate E).
    pathological = "a" * 300 + ".com"
    with pytest.raises(ApiException) as exc_info:
        normalize_hostname(pathological, None)
    assert exc_info.value.code == ErrorCode.INVALID_HOSTNAME
    assert len(exc_info.value.message) < 120
    assert exc_info.value.message.endswith("…' is not a valid hostname.")


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


# --- docs/Fix headers and incomplete.md: HTTP redirect-probe starvation ---


def test_http_redirect_probe_timeout_is_well_under_the_module_budget() -> None:
    # Regression guard for the letshego.com finding: port 80 silently
    # black-holing the TCP connect (no RST, no response — not a fast
    # refusal) must not be able to consume the module's entire timeout
    # budget before the unrelated, working HTTPS probe even gets a turn.
    assert HTTP_REDIRECT_PROBE_TIMEOUT_SECONDS < PER_MODULE_TIMEOUT_SECONDS / 2


@pytest.mark.asyncio
async def test_safe_get_degrades_gracefully_on_a_redirect_to_a_disallowed_port(
    require_internet: None,
) -> None:
    # Regression guard for the tls-v1-0.badssl.com finding: badssl.com's own
    # infrastructure genuinely redirects :443 -> :1010 for this fixture, a
    # port outside contract §10's allowlist. The old behaviour discarded the
    # real, already-fetched :443 response and raised, taking the whole
    # headers module down. The redirect target being disallowed must stop
    # the chain and return what was actually observed, not blow up the call.
    result = await safe_get("https", "tls-v1-0.badssl.com", 443, "/")
    assert result.final_url == "https://tls-v1-0.badssl.com:443/"
    assert result.status_code == 301
    assert result.headers.get("location") == "https://tls-v1-0.badssl.com:1010/"


@pytest.mark.asyncio
async def test_safe_get_bounds_a_hanging_client_close(require_internet: None) -> None:
    """docs/fix_connection_footprint.md Step 1 (audited class-wide): anyio's
    TLSStream.aclose() — what httpx.AsyncClient.aclose() calls for a TLS
    connection — performs the TLS close handshake (unwrap()), which reads
    for the peer's close_notify with no bound of its own; httpx's own
    `timeout=` covers connect/read/write/pool, never close. Confirmed by
    actually making the close hang and asserting safe_get still returns
    promptly, not by reading the code — this is the same bug shape
    chain.py's original one was, just through httpx/anyio's stack."""

    async def _hang(self: httpx.AsyncClient) -> None:
        await asyncio.Event().wait()

    started = time.monotonic()
    with patch.object(httpx.AsyncClient, "aclose", new=_hang):
        result = await safe_get("https", "google.com", 443, "/")
    elapsed = time.monotonic() - started

    assert result.status_code < 500
    assert elapsed < CONNECTION_CLOSE_TIMEOUT_SECONDS + 5


# --- docs/Fix headers and incomplete.md Step 3: classify_module_exception ---


def _with_cause(exc: Exception, cause: BaseException) -> Exception:
    exc.__cause__ = cause
    return exc


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        # asyncio.TimeoutError is an alias of the builtin TimeoutError since
        # Python 3.11 — one case covers both.
        (TimeoutError("boom"), ModuleErrorCode.MODULE_TIMEOUT),
        (httpx.ConnectTimeout("boom"), ModuleErrorCode.MODULE_TIMEOUT),
        (httpx.ReadTimeout("boom"), ModuleErrorCode.MODULE_TIMEOUT),
        (httpx.PoolTimeout("boom"), ModuleErrorCode.MODULE_TIMEOUT),
        (
            ApiException(ErrorCode.BLOCKED_TARGET, "nope", None),
            ModuleErrorCode.BLOCKED_REDIRECT_TARGET,
        ),
        (HostnameResolutionError("example.com"), ModuleErrorCode.BLOCKED_REDIRECT_TARGET),
        (httpx.TooManyRedirects("boom"), ModuleErrorCode.TOO_MANY_REDIRECTS),
        (ConnectionRefusedError(), ModuleErrorCode.CONNECTION_REFUSED),
        (
            _with_cause(httpx.ConnectError("boom"), OSError(errno.ECONNREFUSED, "refused")),
            ModuleErrorCode.CONNECTION_REFUSED,
        ),
        (ConnectionResetError(), ModuleErrorCode.CONNECTION_RESET),
        (BrokenPipeError(), ModuleErrorCode.CONNECTION_RESET),
        (
            _with_cause(httpx.ReadError("boom"), OSError(errno.ECONNRESET, "reset")),
            ModuleErrorCode.CONNECTION_RESET,
        ),
        (ssl.SSLError("boom"), ModuleErrorCode.TLS_ERROR),
        (openssl_ssl.Error("boom"), ModuleErrorCode.TLS_ERROR),
        (httpx.RemoteProtocolError("boom"), ModuleErrorCode.HTTP_ERROR),
        (OSError("some other os error"), ModuleErrorCode.HTTP_ERROR),
        (ValueError("nothing to do with networking"), ModuleErrorCode.UNEXPECTED_ERROR),
    ],
)
def test_classify_module_exception(exc: Exception, expected: ModuleErrorCode) -> None:
    assert classify_module_exception(exc) == expected
