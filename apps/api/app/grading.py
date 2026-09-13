"""The scoring algorithm (contract §9) — implemented exactly once, here.

Pure functions only: no I/O, no clock reads, no network. Nothing in §9
depends on the current time, so no `now` parameter is threaded through —
determinism here comes from taking every finding and module status as
already-computed input, not from avoiding a specific clock call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.enums import Grade, ModuleName, ModuleStatus, Severity
from app.schemas import Finding

# --- Step 1: module score ---

SEVERITY_DEDUCTIONS: dict[Severity, int] = {
    Severity.CRITICAL: 45,
    Severity.HIGH: 25,
    Severity.MEDIUM: 10,
    Severity.LOW: 4,
    Severity.INFO: 0,
}


def score_module(findings: Sequence[Finding]) -> int:
    score = 100
    for finding in findings:
        score -= SEVERITY_DEDUCTIONS[finding.severity]
    return max(0, min(100, score))


def has_critical(findings: Sequence[Finding]) -> bool:
    return any(finding.severity == Severity.CRITICAL for finding in findings)


def status_for_findings(findings: Sequence[Finding]) -> ModuleStatus:
    """Not part of §9's scoring math, but the natural sibling of it: a
    module's operational status (as opposed to "error"/"skipped", which the
    module itself sets when it couldn't run at all) is derived generically
    from what it found — the one example the contract gives (§6.2: a single
    high-severity finding paired with status "warn") is consistent with this
    rule and with no other rule."""
    if has_critical(findings):
        return ModuleStatus.FAIL
    if findings:
        return ModuleStatus.WARN
    return ModuleStatus.OK


# --- Step 2: overall score, weighted mean with re-normalisation ---

MODULE_WEIGHTS: dict[ModuleName, int] = {
    ModuleName.CERTIFICATE: 30,
    ModuleName.TLS: 22,
    ModuleName.CHAIN: 16,
    ModuleName.HEADERS: 16,
    ModuleName.EMAIL_AUTH: 8,
    ModuleName.DNS: 8,
    ModuleName.READINESS: 0,
}

# Public (not `_`-prefixed): app/scanner/readiness.py (v3.0) also needs this
# exact set — a module whose only input (another module's result) never
# completed is itself un-scoreable the same way an errored module is, and
# there must be exactly one definition of "un-scoreable status", not two.
DROPPED_STATUSES = frozenset({ModuleStatus.ERROR, ModuleStatus.SKIPPED})


@dataclass(frozen=True)
class ModuleScoreInput:
    module: ModuleName
    status: ModuleStatus
    findings: Sequence[Finding]


def compute_overall_score(
    module_inputs: Sequence[ModuleScoreInput],
) -> tuple[int, dict[ModuleName, int]]:
    """Weighted mean of module scores. A module with status "error" or
    "skipped" is dropped and the remaining weights re-normalised."""
    module_scores: dict[ModuleName, int] = {}
    weighted_sum = 0
    weight_total = 0
    for item in module_inputs:
        score = score_module(item.findings)
        module_scores[item.module] = score
        if item.status in DROPPED_STATUSES:
            continue
        weight = MODULE_WEIGHTS[item.module]
        weighted_sum += score * weight
        weight_total += weight

    overall = round(weighted_sum / weight_total) if weight_total > 0 else 0
    return overall, module_scores


# --- Step 3: grade bands ---

_GRADE_BANDS: tuple[tuple[int, Grade], ...] = (
    (95, Grade.A_PLUS),
    (88, Grade.A),
    (78, Grade.B),
    (68, Grade.C),
    (55, Grade.D),
    (40, Grade.E),
    (0, Grade.F),
)

GRADE_ORDER: tuple[Grade, ...] = (
    Grade.A_PLUS,
    Grade.A,
    Grade.B,
    Grade.C,
    Grade.D,
    Grade.E,
    Grade.F,
)


def grade_for_score(score: int) -> Grade:
    for threshold, grade in _GRADE_BANDS:
        if score >= threshold:
            return grade
    return Grade.F


def _cap_grade(grade: Grade, cap: Grade) -> Grade:
    """The worse of `grade` and `cap` — a cap can only make a grade worse,
    never better."""
    return grade if GRADE_ORDER.index(grade) >= GRADE_ORDER.index(cap) else cap


# --- Step 4: overrides ---

# Gate A follow-up A4: domain-registration-expiry findings are real and
# urgent, but they're not a TLS failure, and a stale or oddly-formatted WHOIS
# record (common on .in/.co.in and privacy-protected domains — most of this
# product's market) must never be able to force a healthy TLS setup down to
# an F or a C on its own. They still appear in the findings list at their
# own severity and still count toward their module's score (Step 1) — only
# the grade-cap overrides below exclude them.
GRADE_CAP_EXCLUDED_CODES = frozenset({"DOMAIN_EXPIRING_CRITICAL", "DOMAIN_EXPIRING_SOON"})


def _grade_cap_relevant(findings: Sequence[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.code not in GRADE_CAP_EXCLUDED_CODES]


def grade_module(score: int, findings: Sequence[Finding]) -> Grade:
    grade = grade_for_score(score)
    if has_critical(_grade_cap_relevant(findings)):
        grade = Grade.F
    return grade


def compute_overall_grade(score: int, all_findings: Sequence[Finding]) -> Grade:
    cap_relevant = _grade_cap_relevant(all_findings)
    grade = grade_for_score(score)
    if has_critical(cap_relevant):
        grade = Grade.F
    high_count = sum(1 for finding in cap_relevant if finding.severity == Severity.HIGH)
    if high_count >= 2:
        grade = _cap_grade(grade, Grade.C)
    return grade


# --- Step 5: headline ---

_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


def sort_findings(findings: Sequence[Finding]) -> list[Finding]:
    """Contract §6.1: `Scan.findings` is flattened and sorted by severity
    then module."""
    return sorted(findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.module.value))


def worst_finding(findings: Sequence[Finding]) -> Finding | None:
    """The single highest-severity finding, for a module's own `summary`
    text — never just the first one appended, since findings are built in
    whatever order a module happens to check them in, not severity order."""
    if not findings:
        return None
    return sort_findings(findings)[0]


def select_headline(sorted_findings: Sequence[Finding]) -> str:
    if not sorted_findings:
        return "Clean result. Nothing to fix."
    top = sorted_findings[0]
    if top.severity in (Severity.CRITICAL, Severity.HIGH):
        return top.title
    return f"No serious problems found — {len(sorted_findings)} smaller improvements available."


# --- counts ---


def count_by_severity(findings: Sequence[Finding]) -> dict[Severity, int]:
    counts: dict[Severity, int] = dict.fromkeys(Severity, 0)
    for finding in findings:
        counts[finding.severity] += 1
    return counts


# --- top-level orchestration ---


@dataclass(frozen=True)
class ModuleGrading:
    module: ModuleName
    score: int | None
    grade: Grade | None


@dataclass(frozen=True)
class ScanGrading:
    # v3.0 (§9 Step 4b): both `None` exactly when `certificate` is
    # incomplete — see `is_complete`/`incomplete_modules` below. There is no
    # partial or estimated grade in that case, only no grade.
    overall_score: int | None
    overall_grade: Grade | None
    module_grades: dict[ModuleName, ModuleGrading]
    counts: dict[Severity, int]
    findings: list[Finding]
    headline: str
    # v3.0 (§6.1/§9 Step 4b): `is_complete` is false whenever *any* module
    # was dropped (error/skipped) — re-normalisation (Step 2) still runs for
    # every dropped module except `certificate`, so a scan can be "complete
    # enough to grade" and still `is_complete: false`, flagged for the
    # banner rather than silently presented as clean.
    is_complete: bool
    incomplete_modules: list[ModuleName]


# §9 Step 4b: the load-bearing module. Every other module's overall-score
# weight can be dropped and re-normalised (Step 2) without the resulting
# number being dishonest — but a scan is not "gradeable, minus certificate"
# the way it's gradeable minus DNS or email auth. Nothing about *this
# hostname's actual TLS posture* is known without it.
_GRADE_BEARING_MODULE = ModuleName.CERTIFICATE

INCOMPLETE_ASSESSMENT_HEADLINE = (
    "This assessment could not be completed — the certificate check didn't finish, "
    "so there's no grade to show. Try scanning again."
)


def grade_scan(module_inputs: Sequence[ModuleScoreInput]) -> ScanGrading:
    overall_score, module_scores = compute_overall_score(module_inputs)

    module_grades: dict[ModuleName, ModuleGrading] = {}
    all_findings: list[Finding] = []
    incomplete_modules: list[ModuleName] = []
    for item in module_inputs:
        all_findings.extend(item.findings)
        if item.status in DROPPED_STATUSES:
            incomplete_modules.append(item.module)
            module_grades[item.module] = ModuleGrading(module=item.module, score=None, grade=None)
            continue
        score = module_scores[item.module]
        grade = grade_module(score, item.findings)
        module_grades[item.module] = ModuleGrading(module=item.module, score=score, grade=grade)

    sorted_findings = sort_findings(all_findings)
    is_complete = not incomplete_modules

    if _GRADE_BEARING_MODULE in incomplete_modules:
        # Step 4b: no grade at all, not a lower one — the module every other
        # module's weight is normalised around never ran.
        return ScanGrading(
            overall_score=None,
            overall_grade=None,
            module_grades=module_grades,
            counts=count_by_severity(all_findings),
            findings=sorted_findings,
            headline=INCOMPLETE_ASSESSMENT_HEADLINE,
            is_complete=False,
            incomplete_modules=incomplete_modules,
        )

    overall_grade = compute_overall_grade(overall_score, all_findings)

    return ScanGrading(
        overall_score=overall_score,
        overall_grade=overall_grade,
        module_grades=module_grades,
        counts=count_by_severity(all_findings),
        findings=sorted_findings,
        headline=select_headline(sorted_findings),
        is_complete=is_complete,
        incomplete_modules=incomplete_modules,
    )
