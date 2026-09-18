"""Pydantic v2 response models for every shape in contract §6 and §7.1.

Field names are identical to CONTRACT.md — snake_case, no aliases, no
camelCase conversion. This file and `apps/web/types/contract.ts` must be
edited together; see CLAUDE.md rule 4.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.enums import (
    AccountHealth,
    AlertState,
    AlertType,
    BillingInterval,
    BillingProvider,
    Currency,
    DigestMode,
    DmarcPolicy,
    Grade,
    InvoiceState,
    LifetimePhase,
    ModuleErrorCode,
    ModuleName,
    ModuleStatus,
    MonitorState,
    OutreachCampaignStatus,
    OutreachDomainState,
    OutreachProspectState,
    PlanCode,
    ReadinessVerdict,
    ScanStatus,
    Severity,
    SpfPolicy,
    SubscriptionState,
    UserRole,
)
from app.errors import ApiError, ErrorCode

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


class ModuleError(ContractModel):
    """v3.4 (docs/Fix headers and incomplete.md): a structured, safe reason
    a module has `status: "error"` — `code` from the closed
    `ModuleErrorCode` set, `message` plain-language and user-facing. Never a
    traceback, internal hostname, or library name — those go to the
    application log only, against the module and hostname, never this
    field. `app/safety.py`'s `classify_module_exception` is the one place
    an exception is turned into a `code`."""

    code: ModuleErrorCode
    message: str


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
    # v3.4: structured (ModuleError), not a bare string — was `str | None`
    # (the raw `str(exc)`) before this amendment.
    error: ModuleError | None


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

    # v3.3 (§9 Step 4, docs/FIX_GRADING.md — reworded from v3.1): why the
    # critical-finding override forced `overall_grade` to `F` below its own
    # score band ("capped by 1 critical-severity finding"), or why
    # `overall_score` is lower than the diluted weighted mean alone would
    # suggest ("reduced by 2 high-severity findings") — `null` when neither
    # applies, including whenever `overall_grade` itself is null.
    grade_cap_reason: str | None

    # v3.0 (§9 Step 4b): null while `status` isn't "completed" — same
    # not-yet-known convention as `counts` above. Once completed: `false`
    # when any module errored/skipped, `true` otherwise. `overall_grade`/
    # `overall_score` are additionally null (not just `is_complete: false`)
    # specifically when `certificate` is among `incomplete_modules` — every
    # other module's weight re-normalises (§9 Step 2) instead.
    is_complete: bool | None
    incomplete_modules: list[ModuleName] | None

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


# --- 6.6-6.13 Phase 2 data shapes ---


class User(ContractModel):
    user_id: str
    email: str
    email_verified: bool
    created_at: UtcDatetime
    last_login_at: UtcDatetime | None


class Organisation(ContractModel):
    org_id: str
    name: str
    country: str
    currency: Currency
    plan_code: PlanCode
    # Phase 2 Step 5 (contract v2.0 flagged these as this step's own
    # concern). timezone is an IANA zone name; quiet_hours_* are "HH:MM"
    # 24-hour local times.
    timezone: str
    quiet_hours_start: str
    quiet_hours_end: str
    digest_mode: DigestMode
    digest_hour: int
    created_at: UtcDatetime


class Membership(ContractModel):
    org_id: str
    user_id: str
    role: UserRole
    invited_by: str | None
    joined_at: UtcDatetime


class MembershipWithEmail(Membership):
    """Membership (§6.8) plus the member's email — a member list without it
    isn't usable in the dashboard (§Step 7). Not a separate contract shape."""

    email: str


ListItemT = TypeVar("ListItemT", bound=BaseModel)


class PaginatedList(ContractModel, Generic[ListItemT]):
    """§6.14. `per_page` max is 100 — enforced by each router, not here."""

    items: list[ListItemT]
    page: int
    per_page: int
    total: int
    has_more: bool


# --- 7.7 Auth & organisation endpoints (Phase 2 Step 2) ---


class OtpRequestRequest(ContractModel):
    email: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Not a valid email address.")
        return value


class OtpRequestResponse(ContractModel):
    message: str


class OtpVerifyRequest(ContractModel):
    email: str
    code: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Not a valid email address.")
        return value

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("Code must be 6 digits.")
        return value


class LogoutResponse(ContractModel):
    message: str


_QUIET_HOURS_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class OrgUpdateRequest(ContractModel):
    """PATCH body — every field optional (§7.7/§7.12). Only the keys
    actually present in the request are applied (`routers/orgs.py` checks
    `model_fields_set`, same convention as `MonitorUpdateRequest`), so
    `/app/alerts`'s settings form can PATCH quiet hours without also
    resending the org name. `country`/`currency` stay excluded — "changeable
    only before the first subscription" (§Step 6) needs its own lifecycle
    rule, not a plain field-level PATCH."""

    name: str | None = None
    timezone: str | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    digest_mode: DigestMode | None = None
    digest_hour: int | None = Field(default=None, ge=0, le=23)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty.")
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Not a valid IANA timezone name.") from exc
        return value

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _validate_quiet_hours(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _QUIET_HOURS_PATTERN.match(value):
            raise ValueError('Must be "HH:MM" in 24-hour time.')
        return value


class MemberInviteRequest(ContractModel):
    email: str
    role: UserRole

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Not a valid email address.")
        return value


# --- 6.9 / 7.8 Monitored hostnames (Phase 2 Step 3) ---


class MonitoredHostname(ContractModel):
    monitor_id: str
    org_id: str
    hostname: str
    port: int
    state: MonitorState
    label: str | None
    notes: str | None
    last_scan_id: str | None
    last_grade: Grade | None
    last_score: int | None
    last_scanned_at: UtcDatetime | None
    next_scan_at: UtcDatetime | None
    days_until_expiry: int | None
    created_at: UtcDatetime


class MonitorCreateRequest(ContractModel):
    hostname: str
    # None means "not supplied" — same convention as ScanCreateRequest.port
    # (§7.1): app.safety.normalize_hostname applies the 443 default.
    port: int | None = None
    label: str | None = None
    notes: str | None = None


class MonitorUpdateRequest(ContractModel):
    """PATCH body — every field optional. Only the keys actually present in
    the request are applied (routers/monitors.py checks
    `model_fields_set`), so omitting a field leaves it unchanged while
    sending it as `null` clears it. `state` is deliberately narrower than
    the full `MonitorState` enum: `quota_blocked` and `verification_pending`
    are system-managed transitions, not something a PATCH request can set."""

    label: str | None = None
    notes: str | None = None
    state: Literal["active", "paused"] | None = None


class MonitorBulkRequest(ContractModel):
    hostnames: list[str]

    @field_validator("hostnames")
    @classmethod
    def _validate_hostnames(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one hostname is required.")
        if len(value) > 100:
            raise ValueError("At most 100 hostnames per request.")
        return value


class MonitorBulkRow(ContractModel):
    hostname: str
    accepted: bool
    monitor: MonitoredHostname | None
    reason_code: ErrorCode | None
    reason: str | None


class MonitorBulkResponse(ContractModel):
    results: list[MonitorBulkRow]
    accepted_count: int
    rejected_count: int


class MonitorHistoryEntry(ContractModel):
    """§Step 4: `GET /monitors/{monitor_id}/history`'s "grade and score
    timeline" — one row per scan (scheduled or manual) ever run against a
    monitor, newest first. Not a §6 top-level shape of its own; a thin
    projection of the same `Scan` (§6.1) rows already queryable by
    `monitor_id` (`scans.monitor_id`, Step 4)."""

    scan_id: str
    status: ScanStatus
    grade: Grade | None
    score: int | None
    scanned_at: UtcDatetime


# --- 7.10 Alert unsubscribe (Phase 2 Step 5) ---


class UnsubscribeResponse(ContractModel):
    message: str


# --- 6.12/6.13 / 7.11 Billing (Phase 2 Step 6) ---


class Subscription(ContractModel):
    subscription_id: str
    org_id: str
    plan_code: PlanCode
    provider: BillingProvider
    interval: BillingInterval
    currency: Currency
    state: SubscriptionState
    current_period_start: UtcDatetime
    current_period_end: UtcDatetime
    cancel_at_period_end: bool
    provider_subscription_id: str | None


class Invoice(ContractModel):
    invoice_id: str
    org_id: str
    number: str
    amount_minor: int
    currency: Currency
    state: InvoiceState
    issued_at: UtcDatetime
    paid_at: UtcDatetime | None
    pdf_url: str | None
    gstin: str | None
    place_of_supply: str | None


class PricedPlan(ContractModel):
    """§7.11 `GET /billing/plans` row — one per `PlanCode` (§5.1's order),
    always. `purchasable is False` plans (secure/compliance) carry both
    amount fields `null`, never `0`."""

    plan_code: PlanCode
    purchasable: bool
    currency: Currency
    monthly_amount_minor: int | None
    annual_amount_minor: int | None
    hostname_limit: int | None
    scan_interval_hours: int | None
    alert_lead_days: list[int]
    member_limit: int | None


class BillingPlansResponse(ContractModel):
    plans: list[PricedPlan]


class BillingCheckoutRequest(ContractModel):
    plan_code: PlanCode
    interval: BillingInterval
    # India tax fields (§6.13) — optional, captured here because checkout is
    # the one point in this flow where a customer and a purchase meet
    # (CONTRACT.md §7.11 amendment note). Carried through to every Invoice
    # a confirmed subscription later produces.
    gstin: str | None = None
    place_of_supply: str | None = None


class BillingCheckoutResponse(ContractModel):
    checkout_url: str | None
    provider: BillingProvider | None
    contact_us: bool


# --- 6.10/6.11 / 7.12 Alert recipients and monitor alert log (Phase 2 Step 7) ---


class AlertRecipient(ContractModel):
    recipient_id: str
    org_id: str
    monitor_id: str | None
    email: str
    verified: bool
    created_at: UtcDatetime


class AlertRecipientCreateRequest(ContractModel):
    email: str
    # None means org-wide (every monitor) — same convention as the §6.10
    # shape itself, not "not supplied": this field is always meaningful.
    monitor_id: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Not a valid email address.")
        return value


class AlertEvent(ContractModel):
    alert_id: str
    org_id: str
    monitor_id: str
    type: AlertType
    state: AlertState
    severity: Severity
    subject: str
    dedupe_key: str
    scheduled_for: UtcDatetime
    sent_at: UtcDatetime | None
    recipients: list[str]
    payload: dict[str, Any]


# --- 7.13 Admin surface (internal, contract v2.8) ---
#
# Read-models for the operator console. Not customer-facing. Defined inline
# here per the same precedent as MembershipWithEmail (§7.7) and PricedPlan
# (§7.11); mirrored in apps/web/types/contract.ts.


class AdminAccountRow(ContractModel):
    """§7.13 `GET /api/v1/admin/accounts` row. Every derived string
    (`signed_up_relative`, `last_login_relative`) is authored server-side
    (rule 2); the frontend prints it as-is."""

    org_id: str
    name: str
    primary_email: str
    plan_code: PlanCode
    created_at: UtcDatetime
    signed_up_relative: str
    hostname_count: int
    hostname_limit: int | None
    last_login_at: UtcDatetime | None
    last_login_relative: str | None
    last_scan_at: UtcDatetime | None
    worst_grade: Grade | None
    soonest_expiry_at: UtcDatetime | None
    soonest_expiry_days: int | None
    alerts_sent_count: int
    health: AccountHealth
    is_paying: bool


class AdminScans24h(ContractModel):
    completed: int
    failed: int
    queued: int
    running: int
    stuck: int


class AdminSchedulerStatus(ContractModel):
    monitors_due: int
    monitors_overdue: int
    monitors_overdue_1h: int
    last_successful_run_at: UtcDatetime | None


class AdminAlertQueueStatus(ContractModel):
    pending: int
    failed_24h: int


class AdminWorkerStatus(ContractModel):
    queue_depth: int
    # Null = "unknown" (§7.13): not portably obtainable from inside the API
    # process, never guessed.
    memory_mb: int | None


class AdminHealthReport(ContractModel):
    """§7.13 `GET /api/v1/admin/health`."""

    generated_at: UtcDatetime
    scans_24h: AdminScans24h
    scheduler: AdminSchedulerStatus
    alert_queue: AdminAlertQueueStatus
    worker: AdminWorkerStatus
    redis: Literal["ok", "error"]
    postgres: Literal["ok", "error"]
    # v3.5 (docs/urgent_scan_corruption.md Step 4): count of scans in the
    # last 24h with status "failed" but a non-null overall_grade — the exact
    # shape only reachable by a scan completing successfully and then being
    # overwritten afterward (Finding 4). Should always be 0; this is the
    # live canary for that exact bug, or another with the same shape,
    # recurring — nothing else on this page would have caught it, since the
    # scan itself still reports a normal-looking grade everywhere else.
    anomalous_failed_scans_24h: int


class AdminAlertRow(AlertEvent):
    """§7.13: `AlertEvent` (§6.11) plus the resolved monitor hostname, so
    the admin alert-delivery panel is readable without a per-row lookup.
    Same "shape plus one field" pattern as `MembershipWithEmail` (§7.7)."""

    monitor_hostname: str


class AdminScanRow(ContractModel):
    """§7.13: a thin projection of a `scans` row for the account-detail
    scan history — the shareable link is included so the operator can paste
    it straight into an outreach email."""

    scan_id: str
    public_slug: str
    hostname: str
    status: ScanStatus
    grade: Grade | None
    score: int | None
    created_at: UtcDatetime
    share_url: str


class AdminAccountDetail(ContractModel):
    """§7.13 `GET /api/v1/admin/accounts/{org_id}` — one organisation in
    full. `failed_alerts` is a distinct top-level array (not filtered out of
    `recent_alerts`) so the frontend can surface delivery failures at the
    top of the page: a failed alert means the customer thinks they're
    covered and isn't."""

    org: Organisation
    members: list[MembershipWithEmail]
    subscription: Subscription | None
    invoices: list[Invoice]
    monitors: list[MonitoredHostname]
    failed_alerts: list[AdminAlertRow]
    recent_alerts: list[AdminAlertRow]
    recent_scans: list[AdminScanRow]


class AdminFunnelPoint(ContractModel):
    date: IsoDate
    value: int


class AdminFunnelSeries(ContractModel):
    scans_total: list[AdminFunnelPoint]
    # "logged-in" = the scan ran on behalf of an account's monitor
    # (scans.monitor_id non-null); "anonymous" = the public scan box.
    # Documented approximation, §7.13.
    scans_anonymous: list[AdminFunnelPoint]
    scans_logged_in: list[AdminFunnelPoint]
    unique_hostnames: list[AdminFunnelPoint]
    waitlist_signups: list[AdminFunnelPoint]


class AdminFunnelRates(ContractModel):
    # Each is null when its denominator is 0 over the window — never a guess.
    scan_to_waitlist: float | None
    waitlist_to_account: float | None
    account_to_activation: float | None
    account_to_paid: float | None


class AdminFunnelReport(ContractModel):
    """§7.13 `GET /api/v1/admin/funnel` — the Phase 1 acquisition path,
    30 daily points per series plus window-wide conversion rates."""

    generated_at: UtcDatetime
    days: int
    series: AdminFunnelSeries
    rates: AdminFunnelRates


class ProspectBatchCreateRequest(ContractModel):
    label: str
    hostnames: list[str]

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A label is required.")
        return value

    @field_validator("hostnames")
    @classmethod
    def _validate_hostnames(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one hostname is required.")
        if len(value) > 500:
            raise ValueError("At most 500 hostnames per batch.")
        return value


class AdminProspectItem(ContractModel):
    """§7.13. One row of a prospect batch. `accepted: false` rows are only
    ever present in the `POST` response (the rejection is a creation-time
    concern) — `GET .../{batch_id}` returns accepted rows only."""

    hostname: str
    accepted: bool
    reason_code: ErrorCode | None
    scan_id: str | None
    public_slug: str | None
    share_url: str | None
    status: ScanStatus | None
    grade: Grade | None
    days_to_expiry: int | None
    cert_lifetime_days: int | None


class AdminProspectBatchRow(ContractModel):
    """§7.13 `GET /api/v1/admin/prospects` row (the detail below, minus
    `items`). Counts are over accepted hostnames only."""

    batch_id: str
    label: str
    created_at: UtcDatetime
    hostname_count: int
    scans_completed: int
    scans_pending: int
    worst_grade: Grade | None
    expiring_60d_count: int
    over_200day_lifetime_count: int


class AdminProspectBatchDetail(AdminProspectBatchRow):
    items: list[AdminProspectItem]


# --- §7.15 Outreach orchestrator, Stage 1 admin surface (v3.6) ---


class OutreachCampaignCreateRequest(ContractModel):
    name: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A name is required.")
        return value


class OutreachCampaign(ContractModel):
    campaign_id: str
    name: str
    status: OutreachCampaignStatus
    created_at: UtcDatetime


class OutreachCampaignRow(OutreachCampaign):
    """`GET /admin/outreach/campaigns` row. `state_counts` always carries
    every `OutreachProspectState` key, `0` rather than omitted, so a
    missing key never reads as "unknown" (contract rule 7)."""

    prospect_count: int
    state_counts: dict[OutreachProspectState, int]


class OutreachProspectRow(ContractModel):
    """`GET /admin/outreach/campaigns/{campaign_id}/prospects` row — the
    bare list Stage 1 asks for, not the Stage 5 review UI (hook reasoning,
    editable draft, attachments)."""

    prospect_id: str
    agency_name: str
    contact_name: str | None
    contact_email: str
    state: OutreachProspectState
    state_reason: str | None
    domain_count: int
    created_at: UtcDatetime


class OutreachRejectedRow(ContractModel):
    row_number: int
    reason: str


class OutreachImportWarning(ContractModel):
    contact_email: str
    message: str


class OutreachImportReport(ContractModel):
    """§17.5. Nothing imports silently — every count and every rejected or
    suppressed row is accounted for here."""

    imported_agencies: int
    imported_domains: int
    skipped_agencies: int
    suppressed_agencies: int
    rejected_rows: list[OutreachRejectedRow]
    warnings: list[OutreachImportWarning]


# --- §7.16 Outreach orchestrator, Stage 2 admin surface (v3.9/v3.10) ---


class OutreachRecentOutcome(ContractModel):
    domain_id: str
    hostname: str
    prospect_id: str
    agency_name: str
    state: OutreachDomainState  # always one of completed|completed_partial|failed
    scan_error: str | None
    settled_at: UtcDatetime


class OutreachScanMetrics(ContractModel):
    """Step 6, folded into the same live payload as the rest of
    `OutreachScanProgress` rather than a second endpoint — see §7.16."""

    clean_rate: float | None  # COMPLETED / total domains; null only when the campaign has none
    completed_partial_count: int
    completed_partial_by_module_error: dict[str, int]  # ModuleErrorCode keys actually present only
    failed_count: int
    failed_by_reason: dict[str, int]  # grouped by the exact scan_error string
    median_scan_duration_ms: int | None
    p95_scan_duration_ms: int | None
    retried_and_rescued_count: int
    total_wall_time_ms: int | None


class OutreachScanProgress(ContractModel):
    campaign_id: str
    campaign_status: OutreachCampaignStatus
    domain_state_counts: dict[OutreachDomainState, int]  # every key always present, 0 not omitted
    in_flight: int
    started_at: UtcDatetime | None
    estimated_completion_at: UtcDatetime | None
    recent_outcomes: list[OutreachRecentOutcome]
    metrics: OutreachScanMetrics
