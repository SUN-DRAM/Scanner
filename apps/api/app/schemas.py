"""Pydantic v2 response models for every shape in contract §6 and §7.1.

Field names are identical to CONTRACT.md — snake_case, no aliases, no
camelCase conversion. This file and `apps/web/types/contract.ts` must be
edited together; see CLAUDE.md rule 4.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator

from app.enums import (
    DmarcPolicy,
    Grade,
    LifetimePhase,
    ModuleName,
    ModuleStatus,
    ReadinessVerdict,
    ScanStatus,
    Severity,
    SpfPolicy,
)
from app.errors import ApiError

# --- shared scalar types (contract §2.3: ISO 8601 UTC with Z, plain ISO dates) ---

UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ"), return_type=str),
]
IsoDate = Annotated[date, PlainSerializer(lambda d: d.isoformat(), return_type=str)]


class ContractModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- 6.4 certificate.data ---


class CertificateData(ContractModel):
    subject_common_name: str
    subject_alternative_names: list[str]
    issuer_common_name: str
    issuer_organization: str
    serial_number: str
    fingerprint_sha256: str
    not_before: UtcDatetime
    not_after: UtcDatetime
    lifetime_days: int
    days_until_expiry: int
    is_expired: bool
    is_not_yet_valid: bool
    is_self_signed: bool
    is_wildcard: bool
    hostname_matches: bool
    key_algorithm: str
    key_size_bits: int
    signature_algorithm: str
    ocsp_stapling: bool
    sct_count: int


# --- 6.4 chain.data ---


class ChainCertificate(ContractModel):
    position: int
    role: Literal["leaf", "intermediate", "root"]
    subject: str
    issuer: str
    not_after: UtcDatetime


class ChainData(ContractModel):
    chain_length: int
    is_complete: bool
    order_valid: bool
    trusted_root: str | None
    certificates: list[ChainCertificate]


# --- 6.4 tls.data ---


class ProtocolSupport(ContractModel):
    supported: bool
    deprecated: bool


class TlsProtocols(ContractModel):
    tls1_0: ProtocolSupport
    tls1_1: ProtocolSupport
    tls1_2: ProtocolSupport
    tls1_3: ProtocolSupport


class KeyExchangeData(ContractModel):
    """Gate A follow-up A2 (contract §8 `TLS_WEAK_KEY_EXCHANGE`, amendment
    v1.4). Every field nullable when not determinable — `type` comes from
    the negotiated cipher suite name; `bits`/`curve` are not exposed by this
    stack's TLS library (pyOpenSSL has no public getter for the negotiated
    group), so they are always null in practice, never guessed."""

    type: Literal["ECDHE", "DHE"] | None
    bits: int | None
    curve: str | None


class TlsData(ContractModel):
    protocols: TlsProtocols
    negotiated_protocol: str
    negotiated_cipher: str
    weak_ciphers: list[str]
    forward_secrecy: bool
    supports_renegotiation: bool
    key_exchange: KeyExchangeData


# --- 6.4 dns.data ---
# "Any field may be null when the lookup is unavailable (WHOIS often is).
#  null means unknown, never zero." — applies hardest to registrar/domain fields.


class MxRecord(ContractModel):
    priority: int
    host: str


class DnsData(ContractModel):
    a_records: list[str]
    aaaa_records: list[str]
    cname: str | None
    nameservers: list[str]
    mx_records: list[MxRecord]
    caa_records: list[str]
    caa_present: bool
    dnssec_enabled: bool
    registrar: str | None
    domain_created_at: UtcDatetime | None
    domain_expires_at: UtcDatetime | None
    days_until_domain_expiry: int | None


# --- 6.4 email_auth.data ---


class SpfData(ContractModel):
    present: bool
    record: str | None
    policy: SpfPolicy
    lookup_count: int
    issues: list[str]


class DmarcData(ContractModel):
    present: bool
    record: str | None
    policy: DmarcPolicy
    pct: int
    rua_present: bool


class DkimData(ContractModel):
    selectors_checked: list[str]
    selectors_found: list[str]


class EmailAuthData(ContractModel):
    spf: SpfData
    dmarc: DmarcData
    dkim: DkimData


# --- 6.4 headers.data ---


class HstsData(ContractModel):
    present: bool
    max_age_seconds: int | None
    include_subdomains: bool
    preload: bool


class HeaderPresence(ContractModel):
    """Shared shape for the simple present/value headers (CSP, XFO, XCTO, referrer, permissions)."""

    present: bool
    value: str | None


class HeadersData(ContractModel):
    final_url: str
    status_code: int
    redirect_chain: list[str]
    http_to_https_redirect: bool
    hsts: HstsData
    content_security_policy: HeaderPresence
    x_content_type_options: HeaderPresence
    x_frame_options: HeaderPresence
    referrer_policy: HeaderPresence
    permissions_policy: HeaderPresence
    server_header: str | None
    missing: list[str]


# --- 6.4 readiness.data ---


class ReadinessData(ContractModel):
    # Nullable only when verdict == "unknown" (the certificate module
    # errored, so nothing about its lifetime is knowable — never guessed).
    # The contract's §6.4 example only shows the happy path; every other
    # field here is pure time arithmetic or verdict text, computable either
    # way, so those stay required.
    current_lifetime_days: int | None
    current_phase: LifetimePhase
    phase_label: str
    next_deadline: IsoDate
    days_until_next_deadline: int
    renewals_per_year_now: int | None
    renewals_per_year_2027: int | None
    renewals_per_year_2029: int | None
    verdict: ReadinessVerdict
    verdict_label: str
    verdict_reason: str
    survives_2027: bool | None
    survives_2029: bool | None
    message: str


# --- 6.3 Finding ---


class Finding(ContractModel):
    code: str
    module: ModuleName
    severity: Severity
    title: str
    description: str
    remediation: str
    evidence: dict[str, Any]
    docs_path: str


# --- 6.2 ModuleResult — uniform wrapper, generic over the module's data shape ---

ModuleDataT = TypeVar("ModuleDataT", bound=BaseModel)


class ModuleResult(ContractModel, Generic[ModuleDataT]):
    module: ModuleName
    status: ModuleStatus
    score: int | None
    grade: Grade | None
    label: str
    summary: str
    checked_at: UtcDatetime
    duration_ms: int
    findings: list[Finding]
    data: ModuleDataT | None
    error: str | None


class Modules(ContractModel):
    """All seven keys are always present, per contract §6.1 — even mid-scan, as null entries."""

    certificate: ModuleResult[CertificateData] | None
    chain: ModuleResult[ChainData] | None
    tls: ModuleResult[TlsData] | None
    dns: ModuleResult[DnsData] | None
    email_auth: ModuleResult[EmailAuthData] | None
    headers: ModuleResult[HeadersData] | None
    readiness: ModuleResult[ReadinessData] | None


# --- 6.1 Scan ---


class SeverityCounts(ContractModel):
    critical: int
    high: int
    medium: int
    low: int
    info: int


class Scan(ContractModel):
    scan_id: str
    public_slug: str
    hostname: str
    port: int
    status: ScanStatus
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    duration_ms: int | None
    cached: bool

    overall_grade: Grade | None
    overall_score: int | None
    headline: str | None
    share_url: str

    counts: SeverityCounts | None

    modules: Modules

    findings: list[Finding]

    error: ApiError | None


# --- 7.1 POST /api/v1/scans ---


class ScanCreateRequest(ContractModel):
    hostname: str
    # None means "not supplied" — distinct from an explicit 443, because §7.2 step 4
    # only falls back to a hostname-embedded :port when the caller didn't supply one.
    # The literal default of 443 is applied by app.safety.normalize_hostname.
    port: int | None = None


class ScanCreateResponse(ContractModel):
    scan_id: str
    public_slug: str
    status: ScanStatus
    poll_url: str
    share_url: str
    cached: bool


# --- 7.5 POST /api/v1/waitlist (Gate B item 1) ---

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WaitlistCreateRequest(ContractModel):
    scan_id: str
    email: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Not a valid email address.")
        return value


class WaitlistCreateResponse(ContractModel):
    hostname: str
    message: str


# --- 6.5 MetaDeadlines — GET /api/v1/meta/deadlines ---


class PhaseInfo(ContractModel):
    phase: LifetimePhase
    effective_from: IsoDate
    max_lifetime_days: int
    dcv_reuse_days: int
    renewals_per_year: int
    active: bool


class NextDeadlineInfo(ContractModel):
    phase: LifetimePhase
    date: IsoDate
    days_remaining: int


class MetaDeadlines(ContractModel):
    generated_at: UtcDatetime
    phases: list[PhaseInfo]
    next_deadline: NextDeadlineInfo
