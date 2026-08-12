"""The `certificate` module — TLS handshake via `cryptography` + pyOpenSSL
(for OCSP stapling, which the stdlib `ssl` module cannot expose). All fields
in contract §6.4 `certificate.data`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import NameOID

from app.enums import ModuleName, Severity
from app.findings import build_finding
from app.safety import open_pinned_tls_handshake, resolve_and_validate
from app.scanner import ScanContext, run_module
from app.schemas import CertificateData, Finding, ModuleResult

LABEL = "Certificate"


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_serial(serial: int) -> str:
    hex_str = format(serial, "x")
    if len(hex_str) % 2:
        hex_str = "0" + hex_str
    return ":".join(hex_str[i : i + 2] for i in range(0, len(hex_str), 2))


def _common_name(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(attrs[0].value) if attrs else ""


def _organization(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    return str(attrs[0].value) if attrs else ""


def _subject_alternative_names(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return list(ext.value.get_values_for_type(x509.DNSName))


def _sct_count(cert: x509.Certificate) -> int:
    try:
        ext = cert.extensions.get_extension_for_class(
            x509.PrecertificateSignedCertificateTimestamps
        )
    except x509.ExtensionNotFound:
        return 0
    return len(ext.value)


def _key_algorithm_and_size(cert: x509.Certificate) -> tuple[str, int]:
    public_key = cert.public_key()
    if isinstance(public_key, rsa.RSAPublicKey):
        return "RSA", public_key.key_size
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        return "ECDSA", public_key.curve.key_size
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        return "Ed25519", 256
    if isinstance(public_key, ed448.Ed448PublicKey):
        return "Ed448", 456
    if isinstance(public_key, dsa.DSAPublicKey):
        return "DSA", public_key.key_size
    return type(public_key).__name__, 0


def _label_matches_hostname(pattern: str, hostname: str) -> bool:
    pattern = pattern.lower()
    hostname = hostname.lower()
    if pattern == hostname:
        return True
    if pattern.startswith("*."):
        suffix = pattern[1:]
        if not hostname.endswith(suffix):
            return False
        remainder = hostname[: -len(suffix)]
        return bool(remainder) and "." not in remainder
    return False


def _hostname_matches(hostname: str, common_name: str, sans: list[str]) -> bool:
    # Modern clients ignore the CN entirely once SANs are present (RFC 6125).
    candidates = sans or ([common_name] if common_name else [])
    return any(_label_matches_hostname(candidate, hostname) for candidate in candidates)


def _chain_weak_signature_findings(
    chain: tuple[x509.Certificate, ...], base_evidence: Mapping[str, Any]
) -> list[Finding]:
    """CERT_WEAK_SIGNATURE (Gate A follow-up A2): applies to every certificate
    in the presented chain except the root. A SHA-1 intermediate is as fatal
    as a SHA-1 leaf; the root is exempt because it's trusted by identity, so
    its own self-signature carries no security meaning. One finding per
    weak certificate, `evidence.position` naming which one (same numbering
    as chain.data.certificates)."""
    findings: list[Finding] = []
    last_index = len(chain) - 1
    for position, cert in enumerate(chain):
        is_root = position == last_index and cert.subject == cert.issuer
        if is_root:
            continue
        signature_hash = cert.signature_hash_algorithm
        if signature_hash is not None and signature_hash.name in ("sha1", "md5"):
            findings.append(
                build_finding(
                    "CERT_WEAK_SIGNATURE",
                    {
                        **base_evidence,
                        "signature_algorithm": cert.signature_algorithm_oid._name,
                        "position": position,
                    },
                )
            )
    return findings


async def _detect(ctx: ScanContext) -> tuple[CertificateData, list[Finding], str]:
    target = await resolve_and_validate(ctx.hostname)
    handshake = await open_pinned_tls_handshake(target.ip, ctx.port, ctx.hostname)
    leaf = handshake.chain[0]

    common_name = _common_name(leaf.subject)
    issuer_common_name = _common_name(leaf.issuer)
    issuer_organization = _organization(leaf.issuer)
    sans = _subject_alternative_names(leaf)
    not_before = leaf.not_valid_before_utc
    not_after = leaf.not_valid_after_utc
    key_algorithm, key_size_bits = _key_algorithm_and_size(leaf)
    is_self_signed = leaf.subject == leaf.issuer
    is_wildcard = any(san.startswith("*.") for san in sans) or common_name.startswith("*.")
    hostname_matches = _hostname_matches(ctx.hostname, common_name, sans)

    data = CertificateData(
        subject_common_name=common_name,
        subject_alternative_names=sans,
        issuer_common_name=issuer_common_name,
        issuer_organization=issuer_organization,
        serial_number=_format_serial(leaf.serial_number),
        fingerprint_sha256=leaf.fingerprint(hashes.SHA256()).hex(),
        not_before=not_before,
        not_after=not_after,
        lifetime_days=(not_after - not_before).days,
        days_until_expiry=(not_after - ctx.now).days,
        is_expired=ctx.now > not_after,
        is_not_yet_valid=ctx.now < not_before,
        is_self_signed=is_self_signed,
        is_wildcard=is_wildcard,
        hostname_matches=hostname_matches,
        key_algorithm=key_algorithm,
        key_size_bits=key_size_bits,
        signature_algorithm=leaf.signature_algorithm_oid._name,
        ocsp_stapling=handshake.ocsp_stapled,
        sct_count=_sct_count(leaf),
    )

    findings: list[Finding] = []
    base_evidence = {"hostname": ctx.hostname}

    if data.is_expired:
        findings.append(
            build_finding("CERT_EXPIRED", {**base_evidence, "not_after": _iso(data.not_after)})
        )
    elif data.is_not_yet_valid:
        findings.append(
            build_finding(
                "CERT_NOT_YET_VALID", {**base_evidence, "not_before": _iso(data.not_before)}
            )
        )
    else:
        expiry_evidence = {
            **base_evidence,
            "not_after": _iso(data.not_after),
            "days_until_expiry": data.days_until_expiry,
        }
        if data.days_until_expiry <= 3:
            findings.append(build_finding("CERT_EXPIRING_CRITICAL", expiry_evidence))
        elif data.days_until_expiry <= 14:
            findings.append(build_finding("CERT_EXPIRING_SOON", expiry_evidence))
        elif data.days_until_expiry <= 30:
            findings.append(build_finding("CERT_EXPIRING_WARN", expiry_evidence))

    if not data.hostname_matches:
        findings.append(build_finding("CERT_HOSTNAME_MISMATCH", base_evidence))

    if data.is_self_signed:
        findings.append(build_finding("CERT_SELF_SIGNED", base_evidence))

    is_weak_key = (data.key_algorithm == "RSA" and data.key_size_bits < 2048) or (
        data.key_algorithm == "ECDSA" and data.key_size_bits < 256
    )
    if is_weak_key:
        findings.append(
            build_finding(
                "CERT_WEAK_KEY",
                {
                    **base_evidence,
                    "key_algorithm": data.key_algorithm,
                    "key_size_bits": data.key_size_bits,
                },
            )
        )

    findings.extend(_chain_weak_signature_findings(handshake.chain, base_evidence))

    if data.lifetime_days > 200:
        findings.append(
            build_finding(
                "CERT_LONG_LIFETIME", {**base_evidence, "lifetime_days": data.lifetime_days}
            )
        )

    if not data.ocsp_stapling:
        findings.append(build_finding("CERT_NO_OCSP_STAPLING", base_evidence))

    critical_findings = [f for f in findings if f.severity == Severity.CRITICAL]
    if critical_findings:
        summary = critical_findings[0].title + "."
    else:
        issuer = data.issuer_organization or data.issuer_common_name or "an unrecognised issuer"
        summary = f"Valid certificate from {issuer}, expiring in {data.days_until_expiry} days."

    return data, findings, summary


async def run(ctx: ScanContext) -> ModuleResult[CertificateData]:
    return await run_module(module=ModuleName.CERTIFICATE, label=LABEL, ctx=ctx, detect=_detect)
