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
