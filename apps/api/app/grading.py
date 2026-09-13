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

# v3.3 (docs/FIX_GRADING.md): `readiness` now carries real weight — Fault B
# was that a module declared weight-0 ("informational only") could still
# veto the overall grade via Step 4's two-high cap, which is incoherent on
# its own terms and backwards commercially (the 2027 readiness verdict is
# this product's differentiator, not a footnote). The other six weights are
# scaled down proportionally from their v1.0 values (30/22/16/16/8/8 * 0.88,
# rounded to sum exactly to 88) to make room, rather than taken from any one
# module disproportionately.
MODULE_WEIGHTS: dict[ModuleName, int] = {
    ModuleName.CERTIFICATE: 27,
    ModuleName.TLS: 19,
    ModuleName.CHAIN: 14,
    ModuleName.HEADERS: 14,
    ModuleName.EMAIL_AUTH: 7,
    ModuleName.DNS: 7,
    ModuleName.READINESS: 12,
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


def compute_weighted_score(
    module_inputs: Sequence[ModuleScoreInput],
) -> tuple[int, dict[ModuleName, int]]:
    """Weighted mean of module scores. A module with status "error" or
    "skipped" is dropped and the remaining weights re-normalised.

    v3.3 (docs/FIX_GRADING.md, Fault A): deducting *within* a module before
    averaging dilutes severity almost to nothing — a high finding costs 25
    points inside `headers`, but `headers` is one of seven modules, so the
    same finding costs the overall score only a few points. This weighted
    mean is no longer the overall score on its own; `compute_global_score`
    below is the other half, and `grade_scan` takes the lower of the two.
    """
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

    weighted = round(weighted_sum / weight_total) if weight_total > 0 else 0
    return weighted, module_scores


# v3.3 (docs/FIX_GRADING.md, Fault A): a scan-wide severity budget, applied
# independently of which module(s) a finding landed in — the discriminator
# the diluted weighted mean above can't provide on its own (two highs and
# eight highs used to both cap the same letter; here they cost 24 and 96
# points respectively). Deliberately smaller per-finding than Step 1's
# per-module deductions (12 vs. 25 for `high`, etc.) since this budget is
# scan-wide rather than one-module-wide — the two are not meant to be the
# same number.
GLOBAL_SEVERITY_DEDUCTIONS: dict[Severity, int] = {
    Severity.CRITICAL: 40,
    Severity.HIGH: 12,
    Severity.MEDIUM: 5,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


def compute_global_score(all_findings: Sequence[Finding]) -> int:
    """The other half of the overall score (see `compute_weighted_score`).

    Excludes the same Gate A follow-up A4 codes the old grade-cap overrides
    excluded (`_grade_cap_relevant`) — a stale or oddly-formatted WHOIS
    record must still never be able to drag a healthy TLS setup down on its
    own, and that guarantee has to survive this amendment, not just the
    override mechanism it used to live in.
    """
    score = 100
    for finding in _grade_cap_relevant(all_findings):
        score -= GLOBAL_SEVERITY_DEDUCTIONS[finding.severity]
    return max(0, min(100, score))


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


def grade_for_score(score: int) -> Grade:
    for threshold, grade in _GRADE_BANDS:
        if score >= threshold:
            return grade
    return Grade.F


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
    """v3.3 (docs/FIX_GRADING.md): the two-or-more-`high` cap is gone —
    `score` (now `min(weighted, global)`, see `grade_scan`) already reflects
    severity concentration on its own, so band(`score`) no longer needs
    patching to make a letter feel right. The one surviving override is
    unconditional: any `critical` finding is a categorical failure, not a
    matter of degree, and forces `F` regardless of what the number says.
    """
    grade = grade_for_score(score)
    if has_critical(_grade_cap_relevant(all_findings)):
        grade = Grade.F
    return grade


_SEVERITY_REASON_LABELS: tuple[tuple[Severity, str], ...] = (
    (Severity.CRITICAL, "critical"),
    (Severity.HIGH, "high"),
    (Severity.MEDIUM, "medium"),
    (Severity.LOW, "low"),
)


def grade_cap_reason(
    overall_score: int, weighted_score: int, global_score: int, all_findings: Sequence[Finding]
) -> str | None:
    """A plain-language reason the letter or the number needs explaining, or
    `None` when there's nothing to add. Two distinct things can be true here
    (docs/FIX_GRADING.md, "one thing to keep" — the old two-high cap is
    gone, but explaining a score is still useful):

    1. The critical-finding override forced `F` below what `overall_score`
       itself bands to (§9 Step 3) — the one remaining case where the
       letter and the score visibly disagree, same as before this
       amendment: `"capped by {n} critical-severity finding(s)"`.
    2. Otherwise, `overall_score` came from the scan-wide severity budget
       (`compute_global_score`) rather than the diluted per-module weighted
       mean — worth surfacing even though the letter and the score agree,
       since it explains *why* the score is lower than a reader averaging
       the module grades in their head would expect:
       `"reduced by {n} {severity}-severity finding(s)"`, naming whichever
       severity tier is actually present, highest first.

    `None` when neither applies — the letter matches its own band and nothing
    but the ordinary weighted mean produced the number.
    """
    cap_relevant = _grade_cap_relevant(all_findings)
    banded = grade_for_score(overall_score)
    final = compute_overall_grade(overall_score, all_findings)
    if banded != final:
        critical_count = sum(1 for finding in cap_relevant if finding.severity == Severity.CRITICAL)
        noun = "finding" if critical_count == 1 else "findings"
        return f"capped by {critical_count} critical-severity {noun}"

    if global_score < weighted_score:
        for severity, label in _SEVERITY_REASON_LABELS:
            count = sum(1 for finding in cap_relevant if finding.severity == severity)
            if count:
                noun = "finding" if count == 1 else "findings"
                return f"reduced by {count} {label}-severity {noun}"

    return None


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


def module_summary(findings: Sequence[Finding], clean_state: str) -> str:
    """A module's own `summary` (contract §6.2) — describes the module's
    overall state first, never leads with a complaint about a module that
    otherwise graded clean.

    docs/PDF_FIXES.md polish: `dns` graded A+ with the summary "DNSSEC is
    not enabled" and `email_auth` graded A+ with "No DKIM selector
    responded" — both are `info`-severity notes (`SEVERITY_DEDUCTIONS`
    above: `info` costs 0 points), so the module is in fact clean, and a top
    grade next to what reads as a complaint is exactly the confusion rule 7
    ("never guess, never mislead") exists to prevent.

    `clean_state` (e.g. "SPF, DMARC and DKIM all look correctly
    configured.") is every module's own no-findings sentence and is used
    verbatim only when there is genuinely nothing to report. It is
    deliberately *not* reused as the lead-in when an `info` finding is
    present — that sentence asserts specifics ("...and DNSSEC both in
    place") that would flatly contradict the very note being appended.
    A neutral "no real problem" lead-in covers every module's info-only
    case correctly instead. Anything `low` or worse is a real problem and
    still leads on its own, unchanged.
    """
    top = worst_finding(findings)
    if top is None:
        return clean_state
    if top.severity == Severity.INFO:
        return f"No significant issues found. {top.title}."
    return top.title + "."


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
    # v3.3 (docs/FIX_GRADING.md, reworded from v3.1's PDF_FIXES.md original):
    # why the letter needed the critical override, or why the score is lower
    # than the diluted weighted mean alone would suggest — `None` when
    # neither applies. See `grade_cap_reason()`'s docstring for the two
    # cases. Always `None` alongside a null `overall_grade`.
    grade_cap_reason: str | None


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
    weighted_score, module_scores = compute_weighted_score(module_inputs)

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
            grade_cap_reason=None,
        )

    # v3.3 (docs/FIX_GRADING.md): the overall score is the lower of the
    # diluted weighted mean and the scan-wide severity budget — whichever
    # one actually reflects how bad this scan is. `min` rather than picking
    # one or the other keeps a clean site's score exactly at the weighted
    # mean (global has nothing to deduct) while letting concentrated
    # severity override dilution the moment it matters.
    global_score = compute_global_score(all_findings)
    overall_score = min(weighted_score, global_score)
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
        grade_cap_reason=grade_cap_reason(
            overall_score, weighted_score, global_score, all_findings
        ),
    )
