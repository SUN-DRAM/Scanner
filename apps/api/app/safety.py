"""SSRF / private-address guard (contract §10) and hostname normalisation (§7.2).

This is the one place scan targets are resolved and validated. Every network
call the scanner modules make (Step 5) goes through `resolve_and_validate`,
`PinnedHostTransport`, `open_pinned_connection` or `safe_get` — never a raw
`httpx.get`/`socket.connect` against a hostname the caller supplied.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import re
import select
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx
import idna
from cryptography import x509
from OpenSSL import SSL as openssl_ssl

from app.config import get_settings
from app.errors import ApiException, ErrorCode

# --- §7.2 hostname normalisation ---

_LABEL_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_SCHEME_PREFIXES = ("https://", "http://")


@dataclass(frozen=True)
class NormalizedHost:
    hostname: str
    port: int


def normalize_hostname(raw_hostname: str, requested_port: int | None) -> NormalizedHost:
    """Applies contract §7.2 in the exact order specified there. Raises
    ApiException(INVALID_HOSTNAME) on any failure."""
    if not isinstance(raw_hostname, str):
        raise ApiException(ErrorCode.INVALID_HOSTNAME, "Hostname must be a string.")

    # 1. Trim whitespace, lowercase.
    value = raw_hostname.strip().lower()
    if not value:
        raise ApiException(ErrorCode.INVALID_HOSTNAME, "Hostname is required.")

    # 2. Strip scheme, then path/query/fragment.
    for prefix in _SCHEME_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    cut = len(value)
    for separator in ("/", "?", "#"):
        idx = value.find(separator)
        if idx != -1:
            cut = min(cut, idx)
    value = value[:cut]
    if not value:
        raise ApiException(ErrorCode.INVALID_HOSTNAME, "Hostname is required.")

    # 3. Strip a trailing dot.
    if value.endswith("."):
        value = value[:-1]

    # 4. Strip :port, use it only if a port was not already supplied.
    embedded_port: int | None = None
    if value.count(":") == 1:
        host_candidate, _, port_str = value.partition(":")
        if host_candidate and port_str.isdigit():
            value = host_candidate
            embedded_port = int(port_str)

    # 5. IDN -> punycode.
    try:
        value = idna.encode(value, uts46=True).decode("ascii")
    except (idna.IDNAError, UnicodeError, ValueError) as exc:
        raise ApiException(
            ErrorCode.INVALID_HOSTNAME,
            f"'{raw_hostname}' is not a valid hostname.",
            {"reason": str(exc)},
        ) from exc

    # 6. Validate: 1-253 chars, at least one dot, labels 1-63 chars.
    if not (1 <= len(value) <= 253) or "." not in value:
        raise ApiException(ErrorCode.INVALID_HOSTNAME, f"'{raw_hostname}' is not a valid hostname.")
    for label in value.split("."):
        if not (1 <= len(label) <= 63) or not _LABEL_PATTERN.match(label):
            raise ApiException(
                ErrorCode.INVALID_HOSTNAME, f"'{raw_hostname}' is not a valid hostname."
            )

    resolved_port = requested_port if requested_port is not None else (embedded_port or 443)
    return NormalizedHost(hostname=value, port=resolved_port)


# --- §10 rule 3: port allowlist ---

ALLOWED_PORTS = frozenset({443, 8443})
# v1.1 amendment: the headers module's plaintext HTTP->HTTPS redirect probe is the
# one permitted use of port 80 (contract §10 rule 3, amendment log v1.1). It must
# not be used for hostname submission, certificate/chain/TLS connections, or
# anything reachable via ALLOWED_PORTS/validate_port below.
REDIRECT_PROBE_ALLOWED_PORTS = frozenset({80, 443, 8443})


def validate_port(port: int, *, allow_redirect_probe_port_80: bool = False) -> None:
    allowed = REDIRECT_PROBE_ALLOWED_PORTS if allow_redirect_probe_port_80 else ALLOWED_PORTS
    if port not in allowed:
        raise ApiException(
            ErrorCode.BLOCKED_TARGET,
            f"Port {port} is not allowed. Only 443 and 8443 can be scanned.",
            {"port": port},
        )


# --- §10 rule 1: full private/reserved range blocklist ---

BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in BLOCKED_NETWORKS)


# --- §10 rule 8: static host denylist ---

STATIC_HOST_DENYLIST: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata.internal",
        "metadata",
    }
)


def _own_infrastructure_hosts() -> frozenset[str]:
    """Hosts derived from our own configured URLs — we never scan ourselves."""
    settings = get_settings()
    hosts: set[str] = set()
    for url in (settings.public_base_url, *settings.cors_origins_list):
        candidate = url if "//" in url else f"//{url}"
        hostname = urlsplit(candidate).hostname
        if hostname:
            hosts.add(hostname.lower())
    return frozenset(hosts)


def is_denylisted_hostname(hostname: str) -> bool:
    denylist = STATIC_HOST_DENYLIST | _own_infrastructure_hosts()
    if hostname in denylist:
        return True
    return any(hostname.endswith(f".{suffix}") for suffix in denylist)


# --- §10 rules 1+2: resolve-then-validate, with IP pinning ---


class HostnameResolutionError(Exception):
    """The hostname does not resolve to anything. Not an HTTP error — contract
    §7.4 says this becomes a Scan with status 'failed' and error.code SCAN_FAILED,
    not a rejected request."""

    def __init__(self, hostname: str) -> None:
        super().__init__(f"'{hostname}' does not resolve.")
        self.hostname = hostname


@dataclass(frozen=True)
class ResolvedTarget:
    hostname: str
    ip: str
    all_ips: tuple[str, ...]


async def _resolve_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        addrinfo = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []

    seen: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        raw_ip = str(sockaddr[0]).split("%")[0]  # strip IPv6 zone index
        try:
            parsed = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        seen[str(parsed)] = parsed
    return list(seen.values())


def _choose_pinned_ip(
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    # Not specified by the contract: prefer IPv4 when both families resolve, for
    # the widest compatibility with the connection helpers below.
    for ip in ips:
        if ip.version == 4:
            return ip
    return ips[0]


async def resolve_and_validate(hostname: str) -> ResolvedTarget:
    """Resolve `hostname`, reject if denylisted or if any resolved address is
    private/reserved (§10 rule 1), and return a single pinned IP to connect to
    (§10 rule 2). Raises ApiException(BLOCKED_TARGET) or HostnameResolutionError.
    """
    if is_denylisted_hostname(hostname):
        raise ApiException(
            ErrorCode.BLOCKED_TARGET, f"'{hostname}' cannot be scanned.", {"hostname": hostname}
        )

    ips = await _resolve_ips(hostname)
    if not ips:
        raise HostnameResolutionError(hostname)

    for ip in ips:
        if is_blocked_ip(ip):
            raise ApiException(
                ErrorCode.BLOCKED_TARGET,
                f"'{hostname}' resolves to a private or reserved address and cannot be scanned.",
                {"hostname": hostname, "ip": str(ip)},
            )

    pinned = _choose_pinned_ip(ips)
    return ResolvedTarget(hostname=hostname, ip=str(pinned), all_ips=tuple(str(ip) for ip in ips))


# --- §10 rule 2: IP-pinned connection helper (raw TCP/TLS, for cert/chain/tls modules) ---

PER_MODULE_TIMEOUT_SECONDS = 8.0


async def open_pinned_connection(
    ip: str,
    port: int,
    *,
    server_hostname: str | None = None,
    ssl_context: ssl.SSLContext | None = None,
    timeout: float = PER_MODULE_TIMEOUT_SECONDS,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to the pinned IP directly — never re-resolves the hostname, closing
    the DNS-rebinding window. `server_hostname` drives TLS SNI and certificate
    hostname verification when `ssl_context` is given."""
    return await asyncio.wait_for(
        asyncio.open_connection(
            host=ip,
            port=port,
            ssl=ssl_context,
            server_hostname=server_hostname if ssl_context is not None else None,
        ),
        timeout=timeout,
    )


# --- §10 rule 2: IP-pinned TLS handshake (pyOpenSSL, for cert/chain/tls modules) ---
#
# The stdlib `ssl` module cannot expose two things certificate.py and chain.py
# need: the full certificate chain as the server actually sent it (not just
# the leaf), and whether the server stapled an OCSP response. pyOpenSSL's
# `Connection.get_peer_cert_chain()` and `set_ocsp_client_callback()` do both.
# Certificate verification is intentionally disabled — this inspects whatever
# the server presents, including invalid certificates; certificate.py decides
# what's wrong with it afterwards.

_PROTOCOL_VERSION_MAP: dict[str, int] = {
    "tls1_0": openssl_ssl.TLS1_VERSION,
    "tls1_1": openssl_ssl.TLS1_1_VERSION,
    "tls1_2": openssl_ssl.TLS1_2_VERSION,
    "tls1_3": openssl_ssl.TLS1_3_VERSION,
}

@dataclass(frozen=True)
class PinnedTlsHandshakeResult:
    chain: tuple[x509.Certificate, ...]  # leaf first, then intermediates, then root if sent
    negotiated_protocol: str
    negotiated_cipher: str
    ocsp_stapled: bool
    supports_renegotiation: bool


def _pump(sock: socket.socket, fn: Any, deadline: float) -> Any:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("TLS handshake timed out")
        try:
            return fn()
        except openssl_ssl.WantReadError:
            ready, _, _ = select.select([sock], [], [], remaining)
            if not ready:
                raise TimeoutError("TLS handshake timed out") from None
        except openssl_ssl.WantWriteError:
            _, ready, _ = select.select([], [sock], [], remaining)
            if not ready:
                raise TimeoutError("TLS handshake timed out") from None


def _do_pinned_tls_handshake(
    ip: str,
    port: int,
    hostname: str,
    timeout: float,
    min_protocol: str | None,
    max_protocol: str | None,
    cipher_list: bytes | None,
) -> PinnedTlsHandshakeResult:
    ocsp_result: dict[str, bool] = {}

    def _ocsp_callback(_conn: Any, ocsp_data: bytes, _data: Any) -> bool:
        ocsp_result["stapled"] = bool(ocsp_data)
        return True

    ctx = openssl_ssl.Context(openssl_ssl.TLS_CLIENT_METHOD)
    ctx.set_verify(openssl_ssl.VERIFY_NONE, lambda *_args: True)
    if min_protocol is not None:
        ctx.set_min_proto_version(_PROTOCOL_VERSION_MAP[min_protocol])
    if max_protocol is not None:
        ctx.set_max_proto_version(_PROTOCOL_VERSION_MAP[max_protocol])
    # This is a scanner deliberately probing what a server actually supports,
    # not a hardened production client — it must not let OpenSSL's own
    # default security level silently refuse a legacy-only server (that's
    # exactly the server we most need an accurate report on). Always widen
    # unless the caller supplied its own cipher list (tls.py's weak-cipher
    # probe already sets its own narrow, deliberately weak list).
    with contextlib.suppress(openssl_ssl.Error):
        ctx.set_cipher_list(cipher_list if cipher_list is not None else b"ALL:@SECLEVEL=0")
    ctx.set_ocsp_client_callback(_ocsp_callback)

    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setblocking(False)
    deadline = time.monotonic() + timeout
    try:
        with contextlib.suppress(BlockingIOError):
            sock.connect((ip, port))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Connection timed out")
        _, writable, _ = select.select([], [sock], [], remaining)
        if not writable:
            raise TimeoutError("Connection timed out")
        connect_error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if connect_error != 0:
            raise OSError(connect_error, f"Connection failed: {connect_error}")

        conn = openssl_ssl.Connection(ctx, sock)
        conn.set_tlsext_host_name(hostname.encode("ascii"))
        conn.set_connect_state()
        conn.request_ocsp()
        _pump(sock, conn.do_handshake, deadline)

        raw_chain = conn.get_peer_cert_chain() or []
        chain = tuple(cert.to_cryptography() for cert in raw_chain)
        negotiated_protocol = conn.get_protocol_version_name()
        negotiated_cipher = conn.get_cipher_name() or ""

        # TLS 1.3 has no renegotiation as a protocol concept — that's an
        # accurate "no", not an untested guess. Below 1.3, attempt one and
        # see if the server accepts it; any failure just means "no".
        supports_renegotiation = False
        if negotiated_protocol != "TLSv1.3":
            with contextlib.suppress(Exception):
                if conn.renegotiate():
                    _pump(sock, conn.do_handshake, deadline)
                    supports_renegotiation = True

        with contextlib.suppress(Exception):
            conn.shutdown()
        conn.close()
    finally:
        with contextlib.suppress(Exception):
            sock.close()

    return PinnedTlsHandshakeResult(
        chain=chain,
        negotiated_protocol=negotiated_protocol,
        negotiated_cipher=negotiated_cipher,
        ocsp_stapled=ocsp_result.get("stapled", False),
        supports_renegotiation=supports_renegotiation,
    )


async def open_pinned_tls_handshake(
    ip: str,
    port: int,
    hostname: str,
    *,
    timeout: float = PER_MODULE_TIMEOUT_SECONDS,
    min_protocol: str | None = None,
    max_protocol: str | None = None,
    cipher_list: bytes | None = None,
) -> PinnedTlsHandshakeResult:
    """`min_protocol`/`max_protocol` (from `"tls1_0"`, `"tls1_1"`, `"tls1_2"`,
    `"tls1_3"`) force a specific protocol version for tls.py's per-version
    probing; leave both `None` for a normal handshake that negotiates
    whatever the client and server agree on by default. `cipher_list` is an
    OpenSSL cipher-list string (e.g. `b"RC4:3DES:eNULL:aNULL:EXPORT"`) for
    tls.py's weak-cipher probe."""
    return await asyncio.wait_for(
        asyncio.to_thread(
            _do_pinned_tls_handshake,
            ip,
            port,
            hostname,
            timeout,
            min_protocol,
            max_protocol,
            cipher_list,
        ),
        timeout=timeout + 1.0,
    )


# --- §10 rule 2: IP-pinned connection helper (httpx, for the headers module) ---


class PinnedHostTransport(httpx.AsyncHTTPTransport):
    """An httpx transport that connects to a pre-resolved, safety-checked IP while
    preserving the original Host header and TLS SNI/certificate-hostname check —
    the httpx/httpcore equivalent of `open_pinned_connection` above."""

    def __init__(self, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pinned_ip = pinned_ip

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_host = request.url.host
        header_names = {name.decode("ascii").lower() for name, _ in request.headers.raw}
        if "host" not in header_names:
            request.headers["host"] = original_host
        pinned_url = request.url.copy_with(host=self._pinned_ip)
        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": original_host},
        )
        return await super().handle_async_request(pinned_request)


# --- §10 rules 4+6: redirect revalidation and response size cap ---

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 512 * 1024


@dataclass(frozen=True)
class SafeFetchResult:
    final_url: str
    status_code: int
    headers: httpx.Headers
    body: bytes
    redirect_chain: list[str]


async def read_capped_body(response: httpx.Response, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) >= max_bytes:
            break
    return bytes(body[:max_bytes])


async def safe_get(
    scheme: Literal["http", "https"],
    hostname: str,
    port: int,
    path: str = "/",
    *,
    timeout: float = PER_MODULE_TIMEOUT_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
    allow_redirect_probe_port_80: bool = False,
) -> SafeFetchResult:
    """GET a URL with resolve-then-validate + IP pinning on every hop, at most
    `max_redirects` hops each individually revalidated, and a response body
    capped at `MAX_RESPONSE_BYTES`. Never sends credentials, never follows to a
    non-HTTP(S) scheme, GET only — no forms, no JavaScript execution.
    """
    current_scheme: Literal["http", "https"] = scheme
    current_hostname = hostname
    current_port = port
    current_path = path or "/"
    redirect_chain: list[str] = []
    response: httpx.Response | None = None
    body = b""

    for _ in range(max_redirects + 1):
        validate_port(current_port, allow_redirect_probe_port_80=allow_redirect_probe_port_80)
        target = await resolve_and_validate(current_hostname)
        url = f"{current_scheme}://{current_hostname}:{current_port}{current_path}"
        redirect_chain.append(url)

        # verify=False on the transport itself, not just the client: with a
        # custom transport, AsyncClient(verify=...) is ignored — it only
        # configures a transport the client would otherwise build itself.
        # Deliberately unverified, like every other connection this scanner
        # makes: the point is to read whatever the server serves and report
        # on it (headers here; certificate/chain validity are
        # certificate.py's and chain.py's job), not to gate content
        # retrieval on trust.
        transport = PinnedHostTransport(pinned_ip=target.ip, verify=False)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            response = await client.get(url)
            try:
                body = await read_capped_body(response)
            finally:
                await response.aclose()

        location = response.headers.get("location") if response.is_redirect else None
        if location:
            next_url = urljoin(url, location)
            parsed = urlsplit(next_url)
            if parsed.scheme not in ("http", "https"):
                raise ApiException(
                    ErrorCode.BLOCKED_TARGET,
                    "Redirect target uses a disallowed scheme.",
                    {"location": location},
                )
            current_scheme = parsed.scheme
            current_hostname = parsed.hostname or current_hostname
            current_port = parsed.port or (443 if current_scheme == "https" else 80)
            current_path = parsed.path or "/"
            if parsed.query:
                current_path = f"{current_path}?{parsed.query}"
            continue

        return SafeFetchResult(
            final_url=url,
            status_code=response.status_code,
            headers=response.headers,
            body=body,
            redirect_chain=redirect_chain,
        )

    # Exhausted max_redirects while still redirecting: stop following, report
    # the last hop actually fetched (contract §10 rule 4 says "at most 5", not
    # that exceeding it is itself a safety violation).
    assert response is not None
    return SafeFetchResult(
        final_url=redirect_chain[-1],
        status_code=response.status_code,
        headers=response.headers,
        body=body,
        redirect_chain=redirect_chain,
    )
