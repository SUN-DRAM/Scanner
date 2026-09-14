"""Builds a fully valid, internally-consistent `Scan` (contract §6.1) for PDF
export tests — every module payload present, so `Scan.model_validate(...)`
never has to guess at a shape the PDF renderer might otherwise choke on.

Default values are lifted from CONTRACT.md §6.1/§6.4's own worked examples
wherever practical, so a fixture disagreeing with the contract's own sample
data would be an obvious tell of a mistake here, not a coincidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.enums import ModuleName, ModuleStatus
from app.schemas import (
    CertificateData,
    ChainCertificate,
    ChainData,
    DkimData,
    DmarcData,
    DnsData,
    EmailAuthData,
    Finding,
    HeaderPresence,
    HeadersData,
    HstsData,
    KeyExchangeData,
    ModuleError,
    ModuleResult,
    Modules,
    ProtocolSupport,
    ReadinessData,
    Scan,
    SeverityCounts,
    SpfData,
    TlsData,
    TlsProtocols,
)

NOW = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)


def make_certificate_data(**overrides: Any) -> CertificateData:
    defaults: dict[str, Any] = {
        "subject_common_name": "example.com",
        "subject_alternative_names": ["example.com", "www.example.com"],
        "issuer_common_name": "R11",
        "issuer_organization": "Let's Encrypt",
        "serial_number": "03:9a:11:22:33",
        "fingerprint_sha256": "a1b2c3d4",
        "not_before": NOW - timedelta(days=78),
        "not_after": NOW + timedelta(days=12),
        "lifetime_days": 90,
        "days_until_expiry": 12,
        "is_expired": False,
        "is_not_yet_valid": False,
        "is_self_signed": False,
        "is_wildcard": False,
        "hostname_matches": True,
        "key_algorithm": "ECDSA",
        "key_size_bits": 256,
        "signature_algorithm": "sha256WithRSAEncryption",
        "ocsp_stapling": False,
        "sct_count": 2,
    }
    defaults.update(overrides)
    return CertificateData(**defaults)


def make_chain_data(**overrides: Any) -> ChainData:
    leaf = ChainCertificate(
        position=0,
        role="leaf",
        subject="example.com",
        issuer="R11",
        not_after=NOW + timedelta(days=12),
    )
    defaults: dict[str, Any] = {
        "chain_length": 2,
        "is_complete": True,
        "order_valid": True,
        "trusted_root": "ISRG Root X1",
        "certificates": [leaf],
    }
    defaults.update(overrides)
    return ChainData(**defaults)


def make_tls_data(**overrides: Any) -> TlsData:
    defaults: dict[str, Any] = {
        "protocols": TlsProtocols(
            tls1_0=ProtocolSupport(supported=False, deprecated=True),
            tls1_1=ProtocolSupport(supported=False, deprecated=True),
            tls1_2=ProtocolSupport(supported=True, deprecated=False),
            tls1_3=ProtocolSupport(supported=True, deprecated=False),
        ),
        "negotiated_protocol": "TLSv1.3",
        "negotiated_cipher": "TLS_AES_256_GCM_SHA384",
        "weak_ciphers": [],
        "forward_secrecy": True,
        "supports_renegotiation": False,
        "key_exchange": KeyExchangeData(type=None, bits=None, curve=None),
    }
    defaults.update(overrides)
    return TlsData(**defaults)


def make_dns_data(**overrides: Any) -> DnsData:
    defaults: dict[str, Any] = {
        "a_records": ["93.184.216.34"],
        "aaaa_records": [],
        "cname": None,
        "nameservers": ["ns1.example.net"],
        "mx_records": [],
        "caa_records": ['0 issue "letsencrypt.org"'],
        "caa_present": True,
        "dnssec_enabled": False,
        "registrar": "GoDaddy.com, LLC",
        "domain_created_at": NOW - timedelta(days=365 * 10),
        "domain_expires_at": NOW + timedelta(days=204),
        "days_until_domain_expiry": 204,
    }
    defaults.update(overrides)
    return DnsData(**defaults)


def make_email_auth_data(**overrides: Any) -> EmailAuthData:
    dmarc = DmarcData(
        present=True, record="v=DMARC1; p=none;", policy="none", pct=100, rua_present=False
    )
    defaults: dict[str, Any] = {
        "spf": SpfData(
            present=True,
            record="v=spf1 include:_spf.google.com ~all",
            policy="softfail",
            lookup_count=4,
            issues=[],
        ),
        "dmarc": dmarc,
        "dkim": DkimData(selectors_checked=["default", "google"], selectors_found=["google"]),
    }
    defaults.update(overrides)
    return EmailAuthData(**defaults)


def make_headers_data(**overrides: Any) -> HeadersData:
    hsts = HstsData(
        present=True, max_age_seconds=31536000, include_subdomains=True, preload=False
    )
    defaults: dict[str, Any] = {
        "final_url": "https://example.com/",
        "status_code": 200,
        "redirect_chain": ["http://example.com/", "https://example.com/"],
        "http_to_https_redirect": True,
        "hsts": hsts,
        "content_security_policy": HeaderPresence(present=False, value=None),
        "x_content_type_options": HeaderPresence(present=True, value="nosniff"),
        "x_frame_options": HeaderPresence(present=False, value=None),
        "referrer_policy": HeaderPresence(present=True, value="strict-origin-when-cross-origin"),
        "permissions_policy": HeaderPresence(present=False, value=None),
        "server_header": "nginx",
        "missing": ["content_security_policy", "x_frame_options", "permissions_policy"],
    }
    defaults.update(overrides)
    return HeadersData(**defaults)


def make_readiness_data(**overrides: Any) -> ReadinessData:
    verdict_reason = (
        "A 90-day Let's Encrypt certificate reissued recently is consistent with an "
        "automated ACME client."
    )
    message = (
        "This hostname is already on a short-lifetime automated cadence and will not be "
        "affected by the March 2027 change."
    )
    defaults: dict[str, Any] = {
        "current_lifetime_days": 90,
        "current_phase": "phase_200",
        "phase_label": "200-day maximum (in force since 15 March 2026)",
        "next_deadline": "2027-03-15",
        "days_until_next_deadline": 184,
        "renewals_per_year_now": 4,
        "renewals_per_year_2027": 4,
        "renewals_per_year_2029": 8,
        "verdict": "automated",
        "verdict_label": "Looks automated",
        "verdict_reason": verdict_reason,
        "survives_2027": True,
        "survives_2029": True,
        "message": message,
    }
    defaults.update(overrides)
    return ReadinessData(**defaults)


def make_module_result(
    module: ModuleName,
    *,
    status: str = ModuleStatus.OK.value,
    score: int | None = 95,
    grade: str | None = "A",
    label: str,
    summary: str,
    data: Any,
    findings: list[Finding] | None = None,
    error: ModuleError | None = None,
) -> ModuleResult[Any]:
    return ModuleResult(
        module=module,
        status=status,
        score=score,
        grade=grade,
        label=label,
        summary=summary,
        checked_at=NOW,
        duration_ms=250,
        findings=findings or [],
        data=data,
        error=error,
    )


def make_finding(
    code: str = "CERT_EXPIRING_SOON",
    *,
    module: str = "certificate",
    severity: str = "high",
    title: str = "Certificate expires in 12 days",
    description: str = (
        "The certificate for example.com is valid until 21 August 2026. Renewal usually needs "
        "to happen before day 30 to leave room for failure."
    ),
    remediation: str = (
        "Set up automated renewal, or renew now and add an expiry alert at 30, 14 and 7 days."
    ),
    evidence: dict[str, Any] | None = None,
    docs_path: str | None = None,
) -> Finding:
    return Finding(
        code=code,
        module=module,
        severity=severity,
        title=title,
        description=description,
        remediation=remediation,
        evidence=evidence if evidence is not None else {"days_until_expiry": 12},
        docs_path=docs_path or f"/docs/findings/{code.lower().replace('_', '-')}",
    )


def default_modules(findings_by_module: dict[str, list[Finding]] | None = None) -> Modules:
    by_module = findings_by_module or {}
    return Modules(
        certificate=make_module_result(
            ModuleName.CERTIFICATE,
            label="Certificate",
            summary="Valid certificate from Let's Encrypt, expiring in 12 days.",
            data=make_certificate_data(),
            findings=by_module.get("certificate", []),
        ),
        chain=make_module_result(
            ModuleName.CHAIN,
            label="Chain",
            summary="Certificate chain is complete and correctly ordered.",
            data=make_chain_data(),
            findings=by_module.get("chain", []),
        ),
        tls=make_module_result(
            ModuleName.TLS,
            label="TLS configuration",
            summary="Modern protocols only, forward secrecy supported.",
            data=make_tls_data(),
            findings=by_module.get("tls", []),
        ),
        dns=make_module_result(
            ModuleName.DNS,
            label="DNS",
            summary="DNS records resolve correctly. DNSSEC is not enabled.",
            data=make_dns_data(),
            findings=by_module.get("dns", []),
        ),
        email_auth=make_module_result(
            ModuleName.EMAIL_AUTH,
            label="Email authentication",
            summary="SPF and DMARC present; DMARC policy is not enforcing.",
            data=make_email_auth_data(),
            findings=by_module.get("email_auth", []),
        ),
        headers=make_module_result(
            ModuleName.HEADERS,
            label="Security headers",
            summary="HSTS present. Content-Security-Policy is missing.",
            data=make_headers_data(),
            findings=by_module.get("headers", []),
        ),
        readiness=make_module_result(
            ModuleName.READINESS,
            label="Readiness",
            summary="Already on a 90-day automated cadence.",
            data=make_readiness_data(),
            findings=by_module.get("readiness", []),
        ),
    )


def make_completed_scan(
    *,
    hostname: str = "example.com",
    findings: list[Finding] | None = None,
    overall_grade: str | None = "A+",
    overall_score: int | None = 98,
    headline: str = "Clean result. Nothing to fix.",
    modules: Modules | None = None,
    scan_id: str | None = None,
    public_slug: str | None = None,
    completed_at: datetime | None = None,
    is_complete: bool = True,
    incomplete_modules: list[str] | None = None,
    grade_cap_reason: str | None = None,
) -> Scan:
    findings = findings or []
    counts = SeverityCounts(
        critical=sum(1 for f in findings if f.severity == "critical"),
        high=sum(1 for f in findings if f.severity == "high"),
        medium=sum(1 for f in findings if f.severity == "medium"),
        low=sum(1 for f in findings if f.severity == "low"),
        info=sum(1 for f in findings if f.severity == "info"),
    )
    _severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_findings = sorted(findings, key=lambda f: (_severity_order[f.severity], f.module))

    resolved_completed_at = completed_at or NOW
    # A fixed fallback slug (e.g. the contract's own "k3Xm9Qa2Rt7Z" example)
    # would collide on `scans.public_slug`'s unique constraint the moment two
    # fixture scans are inserted into the same real Postgres in one test run
    # — always fresh per call, exactly like `scan_id`'s own default above.
    resolved_slug = public_slug or uuid.uuid4().hex[:12]
    return Scan(
        scan_id=scan_id or str(uuid.uuid4()),
        public_slug=resolved_slug,
        hostname=hostname,
        port=443,
        status="completed",
        created_at=resolved_completed_at - timedelta(seconds=6),
        started_at=resolved_completed_at - timedelta(seconds=5),
        completed_at=resolved_completed_at,
        duration_ms=5120,
        cached=False,
        overall_grade=overall_grade,
        overall_score=overall_score,
        headline=headline,
        share_url=f"http://localhost:3000/scan/{resolved_slug}",
        grade_cap_reason=grade_cap_reason,
        is_complete=is_complete,
        incomplete_modules=incomplete_modules or [],
        counts=counts,
        modules=modules or default_modules(),
        findings=sorted_findings,
        error=None,
    )


def as_pre_v3_schema_row(
    result: dict[str, Any],
    *,
    module_with_string_error: str | None = None,
    error_message: str = "connection reset by peer",
) -> dict[str, Any]:
    """A `scans.result` row as it would have been written before v3.0
    (`is_complete`/`incomplete_modules`), v3.1/v3.3 (`grade_cap_reason`),
    and v3.4 (structured `ModuleResult.error`) all existed --
    `app.scan_compat.parse_stored_scan` must turn this back into a `Scan`
    without ever raising `ValidationError` (docs/urgent_scan_corruption.md
    Finding 4). Pass `module_with_string_error` to also simulate the pre-v3.4
    shape, where a failed module's `error` was a bare `str(exc)` rather than
    a structured `{code, message}` object."""
    row = dict(result)
    row.pop("is_complete", None)
    row.pop("incomplete_modules", None)
    row.pop("grade_cap_reason", None)
    if module_with_string_error is not None:
        row["modules"] = dict(row["modules"])
        row["modules"][module_with_string_error] = dict(
            row["modules"][module_with_string_error]
        )
        row["modules"][module_with_string_error]["error"] = error_message
    return row


def make_many_findings(count: int) -> list[Finding]:
    """A synthetic finding set spanning many pages (Step 3: "40+ findings")."""
    severities = ["critical", "high", "medium", "low", "info"]
    modules = ["certificate", "chain", "tls", "dns", "email_auth", "headers"]
    findings = []
    for i in range(count):
        severity = severities[i % len(severities)]
        module = modules[i % len(modules)]
        description = (
            f"This is synthetic finding number {i}, generated to exercise page-break "
            f"behaviour across a long findings list. It describes a hypothetical issue "
            f"on the {module} module at {severity} severity."
        )
        remediation = (
            f"Address synthetic issue {i} by following the standard remediation for {module}."
        )
        findings.append(
            make_finding(
                code=f"SYNTHETIC_FINDING_{i}",
                module=module,
                severity=severity,
                title=f"Synthetic finding {i} on {module}",
                description=description,
                remediation=remediation,
                evidence={"index": i},
                docs_path=f"/docs/findings/synthetic-finding-{i}",
            )
        )
    return findings
