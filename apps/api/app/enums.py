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
