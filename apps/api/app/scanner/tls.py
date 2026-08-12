"""The `tls` module — protocol support probed per version, negotiated
cipher, weak-cipher and forward-secrecy detection.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from app.enums import ModuleName
from app.findings import build_finding
from app.grading import worst_finding
from app.safety import open_pinned_tls_handshake, resolve_and_validate
from app.scanner import ScanContext, run_module
from app.schemas import (
    Finding,
    KeyExchangeData,
    ModuleResult,
    ProtocolSupport,
    TlsData,
    TlsProtocols,
)

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

# Contract §8 TLS_WEAK_CIPHER: "RC4, 3DES, NULL, EXPORT, or CBC-only suites".
# OpenSSL's short cipher-suite names encode RC4/DES/NULL/EXPORT directly
# ("RC4-SHA", "DES-CBC3-SHA", "NULL-SHA", "EXP-RC4-MD5"), but *not* CBC —
# confirmed directly: "AES128-SHA" and "ECDHE-RSA-AES128-SHA" are both
# CBC-mode suites and neither name contains the literal text "CBC" (only
# 3DES's "DES-CBC3-SHA" does, incidentally). AEAD suites, in contrast,
# always name their mode explicitly (GCM/CCM/CHACHA20-POLY1305, or the bare
# "TLS_..." form for TLS 1.3, which is AEAD-only by spec). So "CBC-only" is
# correctly detected as "a real block/stream cipher suite with no AEAD
# marker", not by searching for the text "CBC" itself.
_EXPLICIT_WEAK_MARKERS = ("RC4", "DES", "NULL", "EXP")
_AEAD_MARKERS = ("GCM", "CCM", "CHACHA20", "POLY1305")
_BLOCK_OR_STREAM_CIPHER_MARKERS = ("AES", "CAMELLIA", "SEED", "IDEA")


def classify_weak_cipher(cipher_name: str) -> bool:
    """True if `cipher_name` (an OpenSSL cipher-suite name) is weak per
    contract §8 TLS_WEAK_CIPHER. Pure and offline — see Gate A follow-up A5."""
    name = cipher_name.upper()
    if any(marker in name for marker in _EXPLICIT_WEAK_MARKERS):
        return True
    if any(marker in name for marker in _AEAD_MARKERS):
        return False
    return any(marker in name for marker in _BLOCK_OR_STREAM_CIPHER_MARKERS)


# Contract §8 TLS_WEAK_KEY_EXCHANGE: "DHE parameters < 2048 bits, or ECDHE
# curve < 256 bits". `bits` is None whenever it wasn't determinable (this
# stack's TLS library exposes no negotiated-group getter — see
# schemas.KeyExchangeData) — never guessed, so the finding never fires from
# an unknown key size.
_MIN_DHE_BITS = 2048
_MIN_ECDHE_BITS = 256


def classify_weak_key_exchange(key_exchange_type: str | None, bits: int | None) -> bool:
    """True if `(key_exchange_type, bits)` is weak per contract §8
    TLS_WEAK_KEY_EXCHANGE. Pure and offline — see Gate A follow-up A5."""
    if bits is None:
        return False
    if key_exchange_type == "DHE":
        return bits < _MIN_DHE_BITS
    if key_exchange_type == "ECDHE":
        return bits < _MIN_ECDHE_BITS
    return False


def _key_exchange_type_from_cipher(cipher_name: str) -> Literal["ECDHE", "DHE"] | None:
    """The cipher-suite name reliably names the key-exchange family for
    TLS <= 1.2 ("ECDHE-RSA-...", "DHE-RSA-..."). TLS 1.3 suite names
    (e.g. "TLS_AES_256_GCM_SHA384") don't encode it at all — None there,
    honestly, rather than assumed."""
    name = cipher_name.upper()
    if "ECDHE" in name:
        return "ECDHE"
    if "DHE" in name:
        return "DHE"
    return None


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
    cipher = result.negotiated_cipher or None
    if cipher is not None and not classify_weak_cipher(cipher):
        # The narrowed offer list only contains weak suites, so this
        # shouldn't happen in practice — but the classifier, not the offer
        # list, is the source of truth for what counts as weak.
        return None
    return cipher


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
    key_exchange_type = _key_exchange_type_from_cipher(default_handshake.negotiated_cipher)
    key_exchange = KeyExchangeData(type=key_exchange_type, bits=None, curve=None)

    data = TlsData(
        protocols=protocols,
        negotiated_protocol=default_handshake.negotiated_protocol,
        negotiated_cipher=default_handshake.negotiated_cipher,
        weak_ciphers=weak_ciphers,
        forward_secrecy=forward_secrecy,
        supports_renegotiation=default_handshake.supports_renegotiation,
        key_exchange=key_exchange,
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

    if classify_weak_key_exchange(key_exchange.type, key_exchange.bits):
        findings.append(
            build_finding(
                "TLS_WEAK_KEY_EXCHANGE",
                {
                    **base_evidence,
                    "key_exchange_type": key_exchange.type,
                    "key_exchange_bits": key_exchange.bits,
                },
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
