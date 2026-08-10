"""Tests for the finding catalogue (contract §8)."""

from __future__ import annotations

import pytest

from app.enums import ModuleName, Severity
from app.findings import FINDINGS_BY_CODE, build_finding, docs_path_for

# Exactly the 42 codes from contract §8, grouped by module as in the table.
EXPECTED_CODES: dict[str, tuple[ModuleName, Severity]] = {
    "CERT_EXPIRED": (ModuleName.CERTIFICATE, Severity.CRITICAL),
    "CERT_NOT_YET_VALID": (ModuleName.CERTIFICATE, Severity.CRITICAL),
    "CERT_HOSTNAME_MISMATCH": (ModuleName.CERTIFICATE, Severity.CRITICAL),
    "CERT_SELF_SIGNED": (ModuleName.CERTIFICATE, Severity.CRITICAL),
    "CERT_EXPIRING_CRITICAL": (ModuleName.CERTIFICATE, Severity.CRITICAL),
    "CERT_EXPIRING_SOON": (ModuleName.CERTIFICATE, Severity.HIGH),
    "CERT_EXPIRING_WARN": (ModuleName.CERTIFICATE, Severity.MEDIUM),
    "CERT_WEAK_KEY": (ModuleName.CERTIFICATE, Severity.HIGH),
    "CERT_WEAK_SIGNATURE": (ModuleName.CERTIFICATE, Severity.HIGH),
    "CERT_LONG_LIFETIME": (ModuleName.CERTIFICATE, Severity.MEDIUM),
    "CERT_NO_OCSP_STAPLING": (ModuleName.CERTIFICATE, Severity.LOW),
    "CHAIN_INCOMPLETE": (ModuleName.CHAIN, Severity.HIGH),
    "CHAIN_OUT_OF_ORDER": (ModuleName.CHAIN, Severity.MEDIUM),
    "CHAIN_UNTRUSTED_ROOT": (ModuleName.CHAIN, Severity.CRITICAL),
    "CHAIN_INTERMEDIATE_EXPIRING": (ModuleName.CHAIN, Severity.HIGH),
    "TLS_LEGACY_PROTOCOL": (ModuleName.TLS, Severity.HIGH),
    "TLS_NO_TLS13": (ModuleName.TLS, Severity.LOW),
    "TLS_WEAK_CIPHER": (ModuleName.TLS, Severity.HIGH),
    "TLS_NO_FORWARD_SECRECY": (ModuleName.TLS, Severity.MEDIUM),
    "DNS_NO_CAA": (ModuleName.DNS, Severity.LOW),
    "DNS_NO_DNSSEC": (ModuleName.DNS, Severity.INFO),
    "DOMAIN_EXPIRING_CRITICAL": (ModuleName.DNS, Severity.CRITICAL),
    "DOMAIN_EXPIRING_SOON": (ModuleName.DNS, Severity.HIGH),
    "DNS_SINGLE_NAMESERVER": (ModuleName.DNS, Severity.MEDIUM),
    "SPF_MISSING": (ModuleName.EMAIL_AUTH, Severity.MEDIUM),
    "SPF_WEAK_POLICY": (ModuleName.EMAIL_AUTH, Severity.LOW),
    "SPF_TOO_MANY_LOOKUPS": (ModuleName.EMAIL_AUTH, Severity.MEDIUM),
    "DMARC_MISSING": (ModuleName.EMAIL_AUTH, Severity.MEDIUM),
    "DMARC_POLICY_NONE": (ModuleName.EMAIL_AUTH, Severity.LOW),
    "DKIM_NOT_FOUND": (ModuleName.EMAIL_AUTH, Severity.INFO),
    "HSTS_MISSING": (ModuleName.HEADERS, Severity.HIGH),
    "HSTS_SHORT_MAX_AGE": (ModuleName.HEADERS, Severity.MEDIUM),
    "NO_HTTPS_REDIRECT": (ModuleName.HEADERS, Severity.HIGH),
    "CSP_MISSING": (ModuleName.HEADERS, Severity.MEDIUM),
    "XFO_MISSING": (ModuleName.HEADERS, Severity.LOW),
    "XCTO_MISSING": (ModuleName.HEADERS, Severity.LOW),
    "REFERRER_POLICY_MISSING": (ModuleName.HEADERS, Severity.LOW),
    "PERMISSIONS_POLICY_MISSING": (ModuleName.HEADERS, Severity.INFO),
    "SERVER_VERSION_DISCLOSED": (ModuleName.HEADERS, Severity.LOW),
    "READINESS_MANUAL_2027": (ModuleName.READINESS, Severity.HIGH),
    "READINESS_UNVERIFIED": (ModuleName.READINESS, Severity.MEDIUM),
    "READINESS_OK": (ModuleName.READINESS, Severity.INFO),
}


def test_catalogue_has_exactly_the_42_contract_codes() -> None:
    assert set(FINDINGS_BY_CODE.keys()) == set(EXPECTED_CODES.keys())
    assert len(FINDINGS_BY_CODE) == 42


@pytest.mark.parametrize("code", list(EXPECTED_CODES.keys()))
def test_catalogue_entry_matches_contract_module_and_severity(code: str) -> None:
    expected_module, expected_severity = EXPECTED_CODES[code]
    definition = FINDINGS_BY_CODE[code]
    assert definition.module == expected_module
    assert definition.severity == expected_severity


def test_docs_path_is_lowercase_hyphenated() -> None:
    assert docs_path_for("CERT_EXPIRING_SOON") == "/docs/findings/cert-expiring-soon"
    assert docs_path_for("DNS_NO_CAA") == "/docs/findings/dns-no-caa"


def test_build_finding_matches_contract_example() -> None:
    finding = build_finding(
        "CERT_EXPIRING_SOON",
        {
            "hostname": "example.com",
            "not_after": "2026-08-21T09:00:00Z",
            "days_until_expiry": 12,
        },
    )
    assert finding.code == "CERT_EXPIRING_SOON"
    assert finding.module == ModuleName.CERTIFICATE
    assert finding.severity == Severity.HIGH
    assert finding.title == "Certificate expires in 12 days"
    assert finding.description == (
        "The certificate for example.com is valid until 21 August 2026. Renewal usually "
        "needs to happen before day 30 to leave room for failure."
    )
    assert finding.remediation == (
        "Set up automated renewal, or renew now and add an expiry alert at 30, 14 and 7 days."
    )
    assert finding.evidence == {
        "hostname": "example.com",
        "not_after": "2026-08-21T09:00:00Z",
        "days_until_expiry": 12,
    }
    assert finding.docs_path == "/docs/findings/cert-expiring-soon"


def test_build_finding_raises_clear_error_for_unknown_code() -> None:
    with pytest.raises(ValueError, match="not a known finding code"):
        build_finding("NOT_A_REAL_CODE", {})


def test_build_finding_raises_clear_error_for_missing_evidence() -> None:
    with pytest.raises(ValueError, match="missing evidence key"):
        build_finding("CERT_EXPIRING_SOON", {"hostname": "example.com"})


def test_build_finding_allows_severity_override() -> None:
    finding = build_finding(
        "DNS_NO_DNSSEC", {"hostname": "example.com"}, severity=Severity.MEDIUM
    )
    assert finding.severity == Severity.MEDIUM
