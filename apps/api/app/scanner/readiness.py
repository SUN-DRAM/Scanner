"""The `readiness` module — the phase constants, the countdown, and the
verdict rules from contract §6.4. This is the product's signature output.

Unlike the other six modules, `run()` here takes the certificate module's
own already-computed `ModuleResult` as an extra argument rather than doing
its own independent I/O — readiness is a synthesis of what certificate.py
already found (its lifetime, its issuer), not a second, possibly-divergent
probe of the same certificate. The phase constants and countdown functions
are public because `routers/meta.py` (Step 6) reuses them verbatim for
`GET /api/v1/meta/deadlines` — one source of truth for these dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.enums import LifetimePhase, ModuleName, ReadinessVerdict
from app.findings import build_finding
from app.scanner import ScanContext, run_module
from app.schemas import CertificateData, Finding, ModuleResult, ReadinessData

LABEL = "2027 readiness"

_ACME_ISSUER_MARKERS = (
    "let's encrypt",
    "lets encrypt",
    "zerossl",
    "google trust services",
    "buypass",
)


@dataclass(frozen=True)
class PhaseConstant:
    phase: LifetimePhase
    effective_from: date
    max_lifetime_days: int
    dcv_reuse_days: int
    renewals_per_year: int
    label: str


# The three phases contract §6.5 lists. "pre_2026" (before the first of
# these takes effect) has no cap of its own and is not in this list.
PHASES: tuple[PhaseConstant, ...] = (
    PhaseConstant(
        LifetimePhase.PHASE_200,
        date(2026, 3, 15),
        200,
        200,
        2,
        "200-day maximum (in force since 15 March 2026)",
    ),
    PhaseConstant(
        LifetimePhase.PHASE_100,
        date(2027, 3, 15),
        100,
        100,
        4,
        "100-day maximum (in force since 15 March 2027)",
    ),
    PhaseConstant(
        LifetimePhase.PHASE_47,
        date(2029, 3, 15),
        47,
        10,
        8,
        "47-day maximum (in force since 15 March 2029)",
    ),
)

_PRE_2026_LABEL = "No CA/Browser Forum lifetime cap yet (before 15 March 2026)"


def current_phase(now: datetime) -> LifetimePhase:
    today = now.date()
    active = LifetimePhase.PRE_2026
    for constant in PHASES:
        if today >= constant.effective_from:
            active = constant.phase
    return active


def phase_label(phase: LifetimePhase) -> str:
    for constant in PHASES:
        if constant.phase == phase:
            return constant.label
    return _PRE_2026_LABEL


def next_deadline_constant(now: datetime) -> PhaseConstant:
    """The next upcoming phase transition. Once past every known phase
    (2029+), there is nothing further defined — report the last one."""
    today = now.date()
    for constant in PHASES:
        if today < constant.effective_from:
            return constant
    return PHASES[-1]


def _is_acme_issuer(issuer_organization: str, issuer_common_name: str) -> bool:
    combined = f"{issuer_organization} {issuer_common_name}".lower()
    return any(marker in combined for marker in _ACME_ISSUER_MARKERS)


def _renewals_per_year(lifetime_days: int, cap_days: int) -> int:
    effective = min(lifetime_days, cap_days)
    # A certificate that renews less than once a year (long-lived, manual)
    # still gets renewed eventually — "0 renewals per year" would read as
    # "never renews", which is wrong, not just imprecise.
    return max(1, round(365 / effective))


def _verdict_for(cert_data: CertificateData | None) -> tuple[ReadinessVerdict, str, str]:
    if cert_data is None:
        return (
            ReadinessVerdict.UNKNOWN,
            "Could not be determined",
            "The certificate check did not complete, so renewal automation could not be assessed.",
        )

    lifetime_days = cert_data.lifetime_days
    issuer = (
        cert_data.issuer_organization or cert_data.issuer_common_name or "an unrecognised issuer"
    )

    if lifetime_days <= 100 and _is_acme_issuer(
        cert_data.issuer_organization, cert_data.issuer_common_name
    ):
        return (
            ReadinessVerdict.AUTOMATED,
            "Looks automated",
            f"A {lifetime_days}-day {issuer} certificate reissued recently is consistent with "
            "an automated ACME client.",
        )
    if lifetime_days <= 100:
        return (
            ReadinessVerdict.SEMI_AUTOMATED,
            "Possibly automated",
            f"A {lifetime_days}-day certificate is short enough to suggest automation, but "
            f"{issuer} is not a certificate authority this scan recognises as an ACME provider.",
        )
    return (
        ReadinessVerdict.MANUAL,
        "Looks manual",
        f"A {lifetime_days}-day certificate is longer than the 100-day cap that takes effect "
        "on 15 March 2027, consistent with a manually issued certificate.",
    )


def _message_for(
    verdict: ReadinessVerdict, survives_2027: bool | None, lifetime_days: int | None
) -> str:
    if verdict == ReadinessVerdict.UNKNOWN:
        return (
            "Run the certificate check again to see how this hostname's renewals will be affected."
        )
    if verdict == ReadinessVerdict.AUTOMATED:
        return (
            "This hostname is already on a short-lifetime automated cadence and will not be "
            "affected by the March 2027 change."
        )
    if verdict == ReadinessVerdict.SEMI_AUTOMATED:
        return (
            "This hostname's certificate lifetime already fits the March 2027 cap, but confirm "
            "renewal is actually automated rather than manually tracked."
        )
    # manual
    if survives_2027:
        return (
            "This certificate's lifetime already fits the March 2027 cap, but the renewal "
            "process itself still needs to become automated to keep up."
        )
    return (
        f"This certificate's {lifetime_days}-day lifetime will not be issuable after 15 March "
        "2027 without moving to automated renewal."
    )


async def _detect(
    ctx: ScanContext, certificate_result: ModuleResult[CertificateData]
) -> tuple[ReadinessData, list[Finding], str]:
    now = ctx.now
    phase = current_phase(now)
    next_phase = next_deadline_constant(now)
    days_until_next_deadline = (next_phase.effective_from - now.date()).days

    cert_data = certificate_result.data
    verdict, verdict_label, verdict_reason = _verdict_for(cert_data)

    current_lifetime_days: int | None = None
    renewals_per_year_now: int | None = None
    renewals_per_year_2027: int | None = None
    renewals_per_year_2029: int | None = None
    survives_2027: bool | None = None
    survives_2029: bool | None = None

    if cert_data is not None:
        current_lifetime_days = cert_data.lifetime_days
        renewals_per_year_now = _renewals_per_year(cert_data.lifetime_days, cert_data.lifetime_days)
        renewals_per_year_2027 = _renewals_per_year(cert_data.lifetime_days, 100)
        renewals_per_year_2029 = _renewals_per_year(cert_data.lifetime_days, 47)
        is_automated = verdict == ReadinessVerdict.AUTOMATED
        survives_2027 = cert_data.lifetime_days <= 100 or is_automated
        survives_2029 = cert_data.lifetime_days <= 47 or is_automated

    message = _message_for(verdict, survives_2027, current_lifetime_days)

    data = ReadinessData(
        current_lifetime_days=current_lifetime_days,
        current_phase=phase,
        phase_label=phase_label(phase),
        next_deadline=next_phase.effective_from,
        days_until_next_deadline=days_until_next_deadline,
        renewals_per_year_now=renewals_per_year_now,
        renewals_per_year_2027=renewals_per_year_2027,
        renewals_per_year_2029=renewals_per_year_2029,
        verdict=verdict,
        verdict_label=verdict_label,
        verdict_reason=verdict_reason,
        survives_2027=survives_2027,
        survives_2029=survives_2029,
        message=message,
    )

    findings: list[Finding] = []
    base_evidence = {
        "hostname": ctx.hostname,
        "current_lifetime_days": current_lifetime_days,
        "verdict_reason": verdict_reason,
    }

    if verdict == ReadinessVerdict.MANUAL:
        findings.append(build_finding("READINESS_MANUAL_2027", base_evidence))
    elif verdict == ReadinessVerdict.SEMI_AUTOMATED:
        findings.append(build_finding("READINESS_UNVERIFIED", base_evidence))
    elif verdict == ReadinessVerdict.AUTOMATED:
        findings.append(build_finding("READINESS_OK", base_evidence))

    return data, findings, message


async def run(
    ctx: ScanContext, certificate_result: ModuleResult[CertificateData]
) -> ModuleResult[ReadinessData]:
    async def _bound_detect(context: ScanContext) -> tuple[ReadinessData, list[Finding], str]:
        return await _detect(context, certificate_result)

    return await run_module(module=ModuleName.READINESS, label=LABEL, ctx=ctx, detect=_bound_detect)
