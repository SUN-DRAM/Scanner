"""Every enum in contract §5. Closed sets — do not add values without a contract amendment."""

from __future__ import annotations

from enum import StrEnum


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ModuleStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ModuleErrorCode(StrEnum):
    """v3.4 (docs/Fix headers and incomplete.md, §6.2 `ModuleResult.error`):
    the closed set of reasons a module can fail to complete. Classified from
    the caught exception in `app/scanner/__init__.py`'s `run_module`, using
    `app/safety.py`'s `classify_module_exception` — never a raw traceback,
    hostname, or library name, which stay in the application log only."""

    MODULE_TIMEOUT = "MODULE_TIMEOUT"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    CONNECTION_RESET = "CONNECTION_RESET"
    TLS_ERROR = "TLS_ERROR"
    TOO_MANY_REDIRECTS = "TOO_MANY_REDIRECTS"
    BLOCKED_REDIRECT_TARGET = "BLOCKED_REDIRECT_TARGET"
    HTTP_ERROR = "HTTP_ERROR"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


class Grade(StrEnum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class ModuleName(StrEnum):
    CERTIFICATE = "certificate"
    CHAIN = "chain"
    TLS = "tls"
    DNS = "dns"
    EMAIL_AUTH = "email_auth"
    HEADERS = "headers"
    READINESS = "readiness"


class ReadinessVerdict(StrEnum):
    AUTOMATED = "automated"
    SEMI_AUTOMATED = "semi_automated"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class LifetimePhase(StrEnum):
    PRE_2026 = "pre_2026"
    PHASE_200 = "phase_200"
    PHASE_100 = "phase_100"
    PHASE_47 = "phase_47"


class SpfPolicy(StrEnum):
    NONE = "none"
    NEUTRAL = "neutral"
    SOFTFAIL = "softfail"
    FAIL = "fail"
    ABSENT = "absent"


class DmarcPolicy(StrEnum):
    NONE = "none"
    QUARANTINE = "quarantine"
    REJECT = "reject"
    ABSENT = "absent"


# --- Phase 2 additions (contract v2.0) ---


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class PlanCode(StrEnum):
    FREE = "free"
    WATCH = "watch"
    WATCH_PRO = "watch_pro"
    SECURE = "secure"
    COMPLIANCE = "compliance"


class SubscriptionState(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingProvider(StrEnum):
    RAZORPAY = "razorpay"
    STRIPE = "stripe"


class BillingInterval(StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class Currency(StrEnum):
    INR = "INR"
    USD = "USD"


class AlertType(StrEnum):
    CERT_EXPIRY = "cert_expiry"
    DOMAIN_EXPIRY = "domain_expiry"
    GRADE_REGRESSION = "grade_regression"
    SCAN_FAILURE = "scan_failure"
    NEW_CRITICAL_FINDING = "new_critical_finding"


class AlertChannel(StrEnum):
    EMAIL = "email"


class AlertState(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class MonitorState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    QUOTA_BLOCKED = "quota_blocked"
    VERIFICATION_PENDING = "verification_pending"


class OtpPurpose(StrEnum):
    LOGIN = "login"
    EMAIL_CHANGE = "email_change"


class InvoiceState(StrEnum):
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


class DigestMode(StrEnum):
    IMMEDIATE = "immediate"
    DIGEST = "digest"


# --- Admin dashboard additions (contract v2.8) ---


class AccountHealth(StrEnum):
    """Contract §7.13, admin surface only — never in a customer-facing
    response. Computed in app/admin/health.py from AT_RISK_LOGIN_SILENCE_DAYS
    / DORMANT_LOGIN_SILENCE_DAYS with the precedence documented there.
    "paying" is not a value: a paid account is the separate `is_paying`
    boolean on AdminAccountRow, so a paying-but-quiet customer still reads
    as at_risk/dormant in the Health column."""

    ACTIVATED = "activated"
    STALLED = "stalled"
    AT_RISK = "at_risk"
    DORMANT = "dormant"


# --- Outreach orchestrator additions (contract v3.6) ---
# §7.15, internal admin surface only — never in a customer-facing response.


class OutreachCampaignStatus(StrEnum):
    """CONTRACT GAP, proposed and signed off in-session: not named by
    docs/OUTREACH_BUILD_SPEC.md's own enum list, but §4.1's
    outreach_campaigns.status column needs a closed set. Same pattern as
    InvoiceState/DigestMode. PAUSED must have real teeth in the state
    machine (Step 4): blocks new domain scans being enqueued and new
    drafts being created for that campaign — not a cosmetic label."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"


class OutreachProspectState(StrEnum):
    """Spec §5.1. One row per agency (grouped by contact_email at import)."""

    PENDING = "pending"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    SUPPRESSED = "suppressed"
    DRAFTING = "drafting"
    READY_FOR_REVIEW = "ready_for_review"
    SENT = "sent"
    REPLIED = "replied"
    FAILED = "failed"
    SKIPPED = "skipped"


class OutreachDomainState(StrEnum):
    """Spec §5.2. One row per client domain."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    RETRYING = "retrying"
    FAILED = "failed"


class OutreachMessageState(StrEnum):
    """Spec §5.3. One row per prospect (unique on prospect_id, §11) —
    unused until Stage 4 (templates/PDF/Gmail draft creation)."""

    DRAFTED = "drafted"
    READY_FOR_REVIEW = "ready_for_review"
    SENT = "sent"
    REPLIED = "replied"
    DISCARDED = "discarded"
