"""Tests for the grading algorithm (contract §9), with fixed fixtures asserting
exact numbers — grading must never drift silently between releases."""

from __future__ import annotations

from collections.abc import Sequence

from app.enums import Grade, ModuleName, ModuleStatus, Severity
from app.grading import (
    ModuleScoreInput,
    compute_global_score,
    compute_overall_grade,
    compute_weighted_score,
    count_by_severity,
    grade_cap_reason,
    grade_for_score,
    grade_module,
    grade_scan,
    module_summary,
    score_module,
    select_headline,
    sort_findings,
    status_for_findings,
    worst_finding,
)
from app.schemas import Finding

ALL_MODULES = (
    ModuleName.CERTIFICATE,
    ModuleName.TLS,
    ModuleName.CHAIN,
    ModuleName.HEADERS,
    ModuleName.EMAIL_AUTH,
    ModuleName.DNS,
    ModuleName.READINESS,
)


def _finding(severity: Severity, module: ModuleName, code: str = "TEST_CODE") -> Finding:
    return Finding(
        code=code,
        module=module,
        severity=severity,
        title=f"{code} title",
        description=f"{code} description",
        remediation=f"{code} remediation",
        evidence={},
        docs_path=f"/docs/findings/{code.lower()}",
    )


def _clean_inputs(
    overrides: dict[ModuleName, Sequence[Finding]] | None = None,
) -> list[ModuleScoreInput]:
    overrides = overrides or {}
    return [
        ModuleScoreInput(module=module, status=ModuleStatus.OK, findings=overrides.get(module, []))
        for module in ALL_MODULES
    ]


# --- fixed fixtures required by the phase prompt ---


def test_clean_site_scores_a_plus() -> None:
    result = grade_scan(_clean_inputs())
    assert result.overall_score == 100
    assert result.overall_grade == Grade.A_PLUS
    assert result.headline == "Clean result. Nothing to fix."
    assert result.counts[Severity.CRITICAL] == 0
    assert result.findings == []


def test_expired_certificate_forces_f() -> None:
    cert_finding = _finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED")
    inputs = _clean_inputs({ModuleName.CERTIFICATE: [cert_finding]})

    result = grade_scan(inputs)

    # weighted: 55*27 + 100*(19+14+14+7+7+12) = 1485 + 7300 = 8785/100 -> 88.
    # global (Step 2b, v3.3): 100 - 40 (one critical) = 60. overall = min(88, 60) = 60.
    # 60 bands to D on its own, but the critical override still forces F.
    assert result.overall_score == 60
    assert result.overall_grade == Grade.F
    assert result.module_grades[ModuleName.CERTIFICATE].score == 55
    # Module score 55 alone bands to D, but the module-level critical cap forces F.
    assert result.module_grades[ModuleName.CERTIFICATE].grade == Grade.F
    assert result.headline == cert_finding.title
    assert result.grade_cap_reason == "capped by 1 critical-severity finding"


def test_two_high_findings_reduce_the_score_via_the_global_budget() -> None:
    # v3.3 (docs/FIX_GRADING.md): the old two-high cap is gone. Two highs
    # now cost the *score* 12 points each via Step 2b's global budget,
    # regardless of which modules they landed in — no separate letter-only
    # override needed.
    tls_finding = _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL")
    headers_finding = _finding(Severity.HIGH, ModuleName.HEADERS, "HSTS_MISSING")
    inputs = _clean_inputs(
        {
            ModuleName.TLS: [tls_finding],
            ModuleName.HEADERS: [headers_finding],
        }
    )

    result = grade_scan(inputs)

    weighted, _ = compute_weighted_score(inputs)
    global_score = compute_global_score([tls_finding, headers_finding])
    assert weighted == 92
    assert global_score == 76  # 100 - 12*2
    assert result.overall_score == min(weighted, global_score) == 76
    assert result.overall_grade == Grade.C  # band(76) — not an artificial cap
    assert result.grade_cap_reason == "reduced by 2 high-severity findings"


def test_complete_scan_has_is_complete_true_and_no_incomplete_modules() -> None:
    result = grade_scan(_clean_inputs())
    assert result.is_complete is True
    assert result.incomplete_modules == []


def test_certificate_error_nulls_overall_grade_and_score() -> None:
    # PDF_FIXES.md Fix 2 / contract v3.0 §9 Step 4b: the load-bearing module
    # errored — there is no grade at all, not a lower one via re-normalisation.
    inputs = [
        ModuleScoreInput(module=ModuleName.CERTIFICATE, status=ModuleStatus.ERROR, findings=[]),
        ModuleScoreInput(module=ModuleName.TLS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.CHAIN, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.HEADERS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.EMAIL_AUTH, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.DNS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.READINESS, status=ModuleStatus.SKIPPED, findings=[]),
    ]

    result = grade_scan(inputs)

    assert result.overall_grade is None
    assert result.overall_score is None
    assert result.is_complete is False
    assert set(result.incomplete_modules) == {ModuleName.CERTIFICATE, ModuleName.READINESS}
    assert result.headline == (
        "This assessment could not be completed — the certificate check didn't finish, "
        "so there's no grade to show. Try scanning again."
    )
    assert result.module_grades[ModuleName.CERTIFICATE].grade is None
    assert result.module_grades[ModuleName.CERTIFICATE].score is None


def test_certificate_skipped_also_nulls_overall_grade() -> None:
    inputs = _clean_inputs()
    skipped_certificate = ModuleScoreInput(
        module=ModuleName.CERTIFICATE, status=ModuleStatus.SKIPPED, findings=[]
    )
    inputs = [
        skipped_certificate if item.module == ModuleName.CERTIFICATE else item for item in inputs
    ]

    result = grade_scan(inputs)

    assert result.overall_grade is None
    assert result.overall_score is None
    assert result.is_complete is False
    assert result.incomplete_modules == [ModuleName.CERTIFICATE]


def test_non_certificate_module_error_still_computes_a_grade_but_marks_incomplete() -> None:
    # Step 2's re-normalisation is unchanged for a module other than
    # certificate — the numeric result stays exactly as before v3.0 — but
    # the scan must still be flagged incomplete, never presented as clean.
    inputs = [
        ModuleScoreInput(module=ModuleName.CERTIFICATE, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.TLS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.CHAIN, status=ModuleStatus.ERROR, findings=[]),
        ModuleScoreInput(module=ModuleName.HEADERS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.EMAIL_AUTH, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.DNS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.READINESS, status=ModuleStatus.OK, findings=[]),
    ]

    result = grade_scan(inputs)

    assert result.overall_grade is not None
    assert result.overall_score is not None
    assert result.overall_grade == Grade.A_PLUS  # unchanged re-normalisation math
    assert result.is_complete is False
    assert result.incomplete_modules == [ModuleName.CHAIN]


def test_dropped_module_renormalises_correctly() -> None:
    cert_finding = _finding(Severity.MEDIUM, ModuleName.CERTIFICATE, "CERT_LONG_LIFETIME")
    inputs = [
        ModuleScoreInput(
            module=ModuleName.CERTIFICATE, status=ModuleStatus.OK, findings=[cert_finding]
        ),
        ModuleScoreInput(module=ModuleName.TLS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.CHAIN, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.HEADERS, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.EMAIL_AUTH, status=ModuleStatus.OK, findings=[]),
        ModuleScoreInput(module=ModuleName.DNS, status=ModuleStatus.ERROR, findings=[]),
        ModuleScoreInput(module=ModuleName.READINESS, status=ModuleStatus.OK, findings=[]),
    ]

    result = grade_scan(inputs)

    # dns (weight 7) dropped: (90*27 + 100*(19+14+14+7+12)) / 93 = 9030/93 -> 97 (weighted).
    # global (Step 2b): 100 - 5 (one medium) = 95. overall = min(97, 95) = 95.
    weighted, _ = compute_weighted_score(inputs)
    global_score = compute_global_score([cert_finding])
    assert weighted == 97
    assert global_score == 95
    assert result.overall_score == min(weighted, global_score) == 95
    assert result.overall_grade == Grade.A_PLUS  # 95 is still the A+ threshold
    assert result.grade_cap_reason == "reduced by 1 medium-severity finding"
    assert result.module_grades[ModuleName.DNS].score is None
    assert result.module_grades[ModuleName.DNS].grade is None
    assert result.is_complete is False
    assert result.incomplete_modules == [ModuleName.DNS]


# --- granular unit tests ---


def test_score_module_deducts_by_severity_and_clamps_at_zero() -> None:
    findings = [
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE),
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE),
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE),
    ]
    assert score_module(findings) == 0  # 100 - 135, clamped


def test_score_module_info_findings_do_not_deduct() -> None:
    findings = [_finding(Severity.INFO, ModuleName.DNS) for _ in range(5)]
    assert score_module(findings) == 100


def test_grade_for_score_bands() -> None:
    assert grade_for_score(100) == Grade.A_PLUS
    assert grade_for_score(95) == Grade.A_PLUS
    assert grade_for_score(94) == Grade.A
    assert grade_for_score(88) == Grade.A
    assert grade_for_score(87) == Grade.B
    assert grade_for_score(78) == Grade.B
    assert grade_for_score(77) == Grade.C
    assert grade_for_score(68) == Grade.C
    assert grade_for_score(67) == Grade.D
    assert grade_for_score(55) == Grade.D
    assert grade_for_score(54) == Grade.E
    assert grade_for_score(40) == Grade.E
    assert grade_for_score(39) == Grade.F
    assert grade_for_score(0) == Grade.F


def test_module_grade_critical_cap_does_not_apply_without_critical_finding() -> None:
    findings = [_finding(Severity.HIGH, ModuleName.TLS)]
    score = score_module(findings)  # 100 - 25 = 75
    assert grade_module(score, findings) == Grade.C  # 68-77 band, no critical cap involved


def test_compute_overall_grade_never_overrides_without_a_critical_finding() -> None:
    # v3.3 (docs/FIX_GRADING.md): the two-or-more-high cap is gone —
    # compute_overall_grade has exactly one override left (critical forces
    # F), so any number of non-critical findings must band on the score
    # alone, however low that score is.
    findings = [_finding(Severity.HIGH, ModuleName.TLS) for _ in range(5)]
    score = score_module(findings)  # 100 - 125 -> clamped to 0
    grade = compute_overall_grade(score, findings)
    assert grade == grade_for_score(score) == Grade.F  # band(0), not an override


def test_compute_weighted_score_all_modules_dropped_defaults_to_zero() -> None:
    inputs = [
        ModuleScoreInput(module=module, status=ModuleStatus.ERROR, findings=[])
        for module in ALL_MODULES
    ]
    weighted, _ = compute_weighted_score(inputs)
    assert weighted == 0


def test_sort_findings_orders_by_severity_then_module() -> None:
    findings = [
        _finding(Severity.LOW, ModuleName.TLS),
        _finding(Severity.CRITICAL, ModuleName.HEADERS),
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE),
        _finding(Severity.HIGH, ModuleName.DNS),
    ]
    sorted_findings = sort_findings(findings)
    assert [f.module for f in sorted_findings] == [
        ModuleName.CERTIFICATE,
        ModuleName.HEADERS,
        ModuleName.DNS,
        ModuleName.TLS,
    ]


def test_select_headline_uses_top_finding_title_when_critical_or_high() -> None:
    findings = sort_findings([_finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED")])
    assert select_headline(findings) == findings[0].title


def test_select_headline_smaller_improvements_when_no_critical_or_high() -> None:
    findings = sort_findings(
        [_finding(Severity.LOW, ModuleName.DNS), _finding(Severity.MEDIUM, ModuleName.HEADERS)]
    )
    expected = "No serious problems found — 2 smaller improvements available."
    assert select_headline(findings) == expected


def test_select_headline_clean_when_no_findings() -> None:
    assert select_headline([]) == "Clean result. Nothing to fix."


def test_count_by_severity_counts_every_severity_including_zero() -> None:
    findings = [_finding(Severity.HIGH, ModuleName.TLS), _finding(Severity.HIGH, ModuleName.DNS)]
    counts = count_by_severity(findings)
    assert counts[Severity.HIGH] == 2
    assert counts[Severity.CRITICAL] == 0
    assert counts[Severity.INFO] == 0


# --- status_for_findings / worst_finding (added while building Step 5) ---


def test_status_for_findings_fail_on_critical() -> None:
    findings = [_finding(Severity.CRITICAL, ModuleName.CERTIFICATE)]
    assert status_for_findings(findings) == ModuleStatus.FAIL


def test_status_for_findings_warn_on_any_non_critical_finding() -> None:
    findings = [_finding(Severity.LOW, ModuleName.DNS)]
    assert status_for_findings(findings) == ModuleStatus.WARN


def test_status_for_findings_ok_when_empty() -> None:
    assert status_for_findings([]) == ModuleStatus.OK


def test_status_for_findings_matches_contract_example() -> None:
    # Contract §6.2's own example: one high-severity finding paired with
    # status "warn", not "fail".
    findings = [_finding(Severity.HIGH, ModuleName.CERTIFICATE, "CERT_EXPIRING_SOON")]
    assert status_for_findings(findings) == ModuleStatus.WARN


def test_worst_finding_picks_highest_severity_regardless_of_insertion_order() -> None:
    high = _finding(Severity.HIGH, ModuleName.CHAIN, "CHAIN_INCOMPLETE")
    critical = _finding(Severity.CRITICAL, ModuleName.CHAIN, "CHAIN_UNTRUSTED_ROOT")
    # Deliberately appended in the "wrong" order — worst_finding must not
    # just return the first element.
    assert worst_finding([high, critical]) is critical


def test_worst_finding_returns_none_for_empty_list() -> None:
    assert worst_finding([]) is None


# --- module_summary (docs/PDF_FIXES.md polish: summaries led with the
# negative — DNS graded A+ with "DNSSEC is not enabled", email auth graded
# A+ with "No DKIM selector responded") ---


def test_module_summary_uses_clean_state_when_there_are_no_findings() -> None:
    assert module_summary([], "All clear.") == "All clear."


def test_module_summary_leads_with_the_finding_for_a_real_problem() -> None:
    finding = _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL")
    assert module_summary([finding], "All clear.") == "TLS_LEGACY_PROTOCOL title."


def test_module_summary_does_not_lead_with_an_info_only_finding() -> None:
    # The exact bug: an info-only module (zero score deduction, still A+)
    # must not have its summary read like a complaint.
    finding = _finding(Severity.INFO, ModuleName.DNS, "DNS_NO_DNSSEC")
    summary = module_summary([finding], "3 nameservers, CAA and DNSSEC both in place.")
    assert summary == "No significant issues found. DNS_NO_DNSSEC title."
    # Never the old behaviour — a raw info-finding title with no context.
    assert summary != "DNS_NO_DNSSEC title."


def test_module_summary_picks_the_worst_finding_when_info_is_mixed_with_a_real_one() -> None:
    info = _finding(Severity.INFO, ModuleName.EMAIL_AUTH, "EMAIL_NO_DKIM_SELECTOR")
    high = _finding(Severity.HIGH, ModuleName.EMAIL_AUTH, "EMAIL_SPF_MISSING")
    summary = module_summary([info, high], "SPF, DMARC and DKIM all look correctly configured.")
    assert summary == "EMAIL_SPF_MISSING title."


# --- Gate A follow-up A4: domain-expiry findings excluded from grade caps ---


def test_domain_expiring_critical_does_not_force_overall_f_even_if_critical() -> None:
    # Defensive: even a hypothetically-critical domain-expiry finding must
    # never cap the grade, not just today's demoted-to-high severity.
    finding = _finding(Severity.CRITICAL, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL")
    score = score_module([finding])  # 100 - 45 = 55
    grade = compute_overall_grade(score, [finding])
    assert grade == grade_for_score(score)  # banded normally, no F override


def test_domain_expiry_findings_excluded_from_the_global_severity_budget() -> None:
    # v3.3 (docs/FIX_GRADING.md): Step 2b replaces the old two-high cap as
    # the mechanism that could drag a healthy site down from concentrated
    # severity — the A4 guarantee has to survive by excluding these codes
    # from Step 2b's deduction too, not just the old cap.
    findings = [
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL"),
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_SOON"),
    ]
    assert compute_global_score(findings) == 100  # no deduction at all


def test_one_real_high_plus_domain_expiry_high_only_deducts_for_the_real_one() -> None:
    findings = [
        _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL"),
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL"),
    ]
    assert compute_global_score(findings) == 88  # 100 - 12, not - 24


def test_domain_expiring_critical_does_not_force_its_own_module_to_f() -> None:
    finding = _finding(Severity.CRITICAL, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL")
    score = score_module([finding])  # 100 - 45 = 55 -> bands to D
    assert grade_module(score, [finding]) == Grade.D


# --- docs/FIX_GRADING.md v3.3: grade_cap_reason, reworked signature ---
# (overall_score, weighted_score, global_score, all_findings) — the old
# two-high cap is gone, so this now explains one of two things: the
# critical override forcing F below its own band, or Step 2b's severity
# budget (not the diluted weighted mean) having set the score.


def test_grade_cap_reason_is_none_when_nothing_needs_explaining() -> None:
    assert grade_cap_reason(97, 97, 97, []) is None


def test_grade_cap_reason_names_the_critical_override() -> None:
    findings = [_finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED")]
    # 55 bands to D — the critical override forces F regardless.
    assert grade_cap_reason(55, 90, 55, findings) == "capped by 1 critical-severity finding"


def test_grade_cap_reason_pluralises_multiple_critical_findings() -> None:
    findings = [
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED"),
        _finding(Severity.CRITICAL, ModuleName.CHAIN, "CHAIN_UNTRUSTED_ROOT"),
    ]
    assert grade_cap_reason(55, 90, 55, findings) == "capped by 2 critical-severity findings"


def test_grade_cap_reason_credits_the_critical_override_over_a_score_reduction() -> None:
    # Both conditions are present; the critical override is the one that
    # actually changed the letter (F either way) — global being the
    # binding score has no visible letter/band change of its own to explain.
    findings = [
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED"),
        _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL"),
        _finding(Severity.HIGH, ModuleName.HEADERS, "HSTS_MISSING"),
    ]
    assert grade_cap_reason(55, 90, 55, findings) == "capped by 1 critical-severity finding"


def test_grade_cap_reason_is_none_when_a_critical_finding_changes_nothing() -> None:
    # The score already bands to F on its own, and global == weighted (the
    # severity budget wasn't the binding constraint either) — nothing to
    # explain on either front.
    findings = [_finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED")]
    assert grade_for_score(10) == Grade.F
    assert grade_cap_reason(10, 10, 10, findings) is None


def test_grade_cap_reason_is_none_when_the_weighted_mean_is_the_binding_score() -> None:
    # A high finding exists, but the diluted weighted mean (not Step 2b's
    # budget) is what actually produced the lower number — nothing about
    # severity concentration to call out.
    findings = [_finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL")]
    assert grade_cap_reason(85, 85, 88, findings) is None


def test_grade_cap_reason_names_a_single_reducing_high_finding() -> None:
    findings = [_finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL")]
    # global (88) < weighted (95) — the budget, not dilution, set the score.
    assert grade_cap_reason(88, 95, 88, findings) == "reduced by 1 high-severity finding"


def test_grade_cap_reason_names_the_highest_severity_tier_present() -> None:
    findings = [
        _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL"),
        _finding(Severity.HIGH, ModuleName.HEADERS, "HSTS_MISSING"),
        _finding(Severity.MEDIUM, ModuleName.DNS, "DNS_SINGLE_NAMESERVER"),
    ]
    assert grade_cap_reason(61, 99, 61, findings) == "reduced by 2 high-severity findings"


def test_grade_cap_reason_excludes_domain_expiry_codes_from_the_reduction_too() -> None:
    # Gate A follow-up A4: these codes are excluded from Step 2b's budget
    # (grading.py's GRADE_CAP_EXCLUDED_CODES) — the reason must agree, even
    # if something else happened to make global < weighted.
    findings = [
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL"),
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_SOON"),
    ]
    assert grade_cap_reason(76, 90, 76, findings) is None
