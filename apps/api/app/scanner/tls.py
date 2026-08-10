"""The `tls` module — protocol support probed per version, negotiated
cipher, weak-cipher and forward-secrecy detection.
"""

from __future__ import annotations

import asyncio

from app.enums import ModuleName
from app.findings import build_finding
from app.grading import worst_finding
from app.safety import open_pinned_tls_handshake, resolve_and_validate
from app.scanner import ScanContext, run_module
from app.schemas import Finding, ModuleResult, ProtocolSupport, TlsData, TlsProtocols

LABEL = "TLS"

_PROTOCOL_KEYS = ("tls1_0", "tls1_1", "tls1_2", "tls1_3")
_PROTOCOL_LABELS = {
    "tls1_0": "TLS 1.0",
    "tls1_1": "TLS 1.1",
    "tls1_2": "TLS 1.2",
    "tls1_3": "TLS 1.3",
}
_DEPRECATED = {"tls1_0": True, "tls1_1": True, "tls1_2": False, "tls1_3": False}
_WEAK_CIPHER_LIST = b"RC4:3DES:eNULL:aNULL:EXPORT"
_FORWARD_SECRET_MARKERS = ("ECDHE", "DHE")


async def _probe_protocol(ip: str, port: int, hostname: str, protocol: str) -> bool:
    try:
        await open_pinned_tls_handshake(
            ip, port, hostname, min_protocol=protocol, max_protocol=protocol
        )
        return True
    except Exception:
        return False


async def _probe_weak_cipher(ip: str, port: int, hostname: str) -> str | None:
    try:
        result = await open_pinned_tls_handshake(
            ip, port, hostname, max_protocol="tls1_2", cipher_list=_WEAK_CIPHER_LIST
        )
    except Exception:
        return None
    return result.negotiated_cipher or None


def _has_forward_secrecy(protocol: str, cipher: str) -> bool:
    if protocol == "TLSv1.3":
        return True
    return any(marker in cipher for marker in _FORWARD_SECRET_MARKERS)


async def _detect(ctx: ScanContext) -> tuple[TlsData, list[Finding], str]:
    target = await resolve_and_validate(ctx.hostname)

    default_handshake, support_results, weak_cipher = await asyncio.gather(
        open_pinned_tls_handshake(target.ip, ctx.port, ctx.hostname),
        asyncio.gather(
            *(_probe_protocol(target.ip, ctx.port, ctx.hostname, key) for key in _PROTOCOL_KEYS)
        ),
        _probe_weak_cipher(target.ip, ctx.port, ctx.hostname),
    )

    support_by_key = dict(zip(_PROTOCOL_KEYS, support_results, strict=True))

    def _support(key: str) -> ProtocolSupport:
        return ProtocolSupport(supported=support_by_key[key], deprecated=_DEPRECATED[key])

    protocols = TlsProtocols(
        tls1_0=_support("tls1_0"),
        tls1_1=_support("tls1_1"),
        tls1_2=_support("tls1_2"),
        tls1_3=_support("tls1_3"),
    )
    weak_ciphers = [weak_cipher] if weak_cipher else []
    forward_secrecy = _has_forward_secrecy(
        default_handshake.negotiated_protocol, default_handshake.negotiated_cipher
    )

    data = TlsData(
        protocols=protocols,
        negotiated_protocol=default_handshake.negotiated_protocol,
        negotiated_cipher=default_handshake.negotiated_cipher,
        weak_ciphers=weak_ciphers,
        forward_secrecy=forward_secrecy,
        supports_renegotiation=default_handshake.supports_renegotiation,
    )

    findings: list[Finding] = []
    base_evidence = {"hostname": ctx.hostname}

    legacy_enabled = [_PROTOCOL_LABELS[key] for key in ("tls1_0", "tls1_1") if support_by_key[key]]
    if legacy_enabled:
        findings.append(
            build_finding(
                "TLS_LEGACY_PROTOCOL", {**base_evidence, "protocol": " and ".join(legacy_enabled)}
            )
        )

    if not support_by_key["tls1_3"]:
        findings.append(build_finding("TLS_NO_TLS13", base_evidence))

    if weak_ciphers:
        findings.append(
            build_finding(
                "TLS_WEAK_CIPHER", {**base_evidence, "weak_ciphers": ", ".join(weak_ciphers)}
            )
        )

    if not forward_secrecy:
        findings.append(
            build_finding(
                "TLS_NO_FORWARD_SECRECY", {**base_evidence, "cipher": data.negotiated_cipher}
            )
        )

    top = worst_finding(findings)
    if top is not None:
        summary = top.title + "."
    else:
        summary = (
            f"{data.negotiated_protocol} with {data.negotiated_cipher}, forward secrecy enabled."
        )

    return data, findings, summary


async def run(ctx: ScanContext) -> ModuleResult[TlsData]:
    return await run_module(module=ModuleName.TLS, label=LABEL, ctx=ctx, detect=_detect)
