"""Tests for the grading algorithm (contract §9), with fixed fixtures asserting
exact numbers — grading must never drift silently between releases."""

from __future__ import annotations

from collections.abc import Sequence

from app.enums import Grade, ModuleName, ModuleStatus, Severity
from app.grading import (
    ModuleScoreInput,
    compute_overall_grade,
    compute_overall_score,
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

    # 55*30 + 100*(22+16+16+8+8) = 1650 + 7000 = 8650 / 100 = 86.5 -> round-half-to-even -> 86
    assert result.overall_score == 86
    assert result.overall_grade == Grade.F
    assert result.module_grades[ModuleName.CERTIFICATE].score == 55
    # Module score 55 alone bands to D, but the critical cap forces F.
    assert result.module_grades[ModuleName.CERTIFICATE].grade == Grade.F
    assert result.headline == cert_finding.title


def test_two_high_findings_cap_overall_at_c() -> None:
    tls_finding = _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL")
    headers_finding = _finding(Severity.HIGH, ModuleName.HEADERS, "HSTS_MISSING")
    inputs = _clean_inputs(
        {
            ModuleName.TLS: [tls_finding],
            ModuleName.HEADERS: [headers_finding],
        }
    )

    result = grade_scan(inputs)

    # 100*30 + 75*22 + 100*16 + 75*16 + 100*8 + 100*8 = 9050 / 100 = 90.5
    # -> round-half-to-even -> 90
    assert result.overall_score == 90
    assert result.overall_grade == Grade.C  # would otherwise band to A
    # PDF_FIXES.md polish: 90 bands to A — the reader must be told why the
    # letter reads three bands worse than that.
    assert result.grade_cap_reason == "capped by 2 high-severity findings"


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

    # dns (weight 8) dropped: (90*30 + 100*22 + 100*16 + 100*16 + 100*8) / 92
    # = 8900/92 = 96.739... -> 97
    assert result.overall_score == 97
    assert result.overall_grade == Grade.A_PLUS
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


def test_double_high_cap_never_upgrades_an_already_worse_grade() -> None:
    # Three highs alone would band well below C; the cap must not pull it up to C.
    findings = [_finding(Severity.HIGH, ModuleName.TLS) for _ in range(5)]
    score = score_module(findings)  # 100 - 125 -> clamped to 0
    grade = compute_overall_grade(score, findings)
    assert grade == Grade.F  # band(0) == F, and F is already worse than the C cap


def test_compute_overall_score_all_modules_dropped_defaults_to_zero() -> None:
    inputs = [
        ModuleScoreInput(module=module, status=ModuleStatus.ERROR, findings=[])
        for module in ALL_MODULES
    ]
    overall, _ = compute_overall_score(inputs)
    assert overall == 0


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


def test_domain_expiry_highs_alone_do_not_trigger_the_two_high_cap() -> None:
    findings = [
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL"),
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_SOON"),
    ]
    score = score_module(findings)
    grade = compute_overall_grade(score, findings)
    assert grade == grade_for_score(score)  # no cap-to-C from two excluded highs


def test_one_real_high_plus_domain_expiry_high_does_not_trigger_the_two_high_cap() -> None:
    findings = [
        _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL"),
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL"),
    ]
    score = score_module(findings)
    grade = compute_overall_grade(score, findings)
    assert grade == grade_for_score(score)  # only one cap-relevant high — cap needs 2+


def test_domain_expiring_critical_does_not_force_its_own_module_to_f() -> None:
    finding = _finding(Severity.CRITICAL, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL")
    score = score_module([finding])  # 100 - 45 = 55 -> bands to D
    assert grade_module(score, [finding]) == Grade.D


# --- PDF_FIXES.md polish: grade_cap_reason ---


def test_grade_cap_reason_is_none_when_the_letter_already_matches_the_score() -> None:
    assert grade_cap_reason(97, []) is None


def test_grade_cap_reason_names_the_two_high_cap() -> None:
    findings = [
        _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL"),
        _finding(Severity.HIGH, ModuleName.HEADERS, "HSTS_MISSING"),
    ]
    # 82 bands to B (78-87) — the two-high cap pulls it to C.
    assert grade_cap_reason(82, findings) == "capped by 2 high-severity findings"


def test_grade_cap_reason_names_the_critical_cap() -> None:
    findings = [_finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED")]
    # 55 bands to D — the critical cap forces F.
    assert grade_cap_reason(55, findings) == "capped by 1 critical-severity finding"


def test_grade_cap_reason_pluralises_multiple_critical_findings() -> None:
    findings = [
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED"),
        _finding(Severity.CRITICAL, ModuleName.CHAIN, "CHAIN_UNTRUSTED_ROOT"),
    ]
    assert grade_cap_reason(55, findings) == "capped by 2 critical-severity findings"


def test_grade_cap_reason_credits_the_critical_cap_over_the_two_high_cap() -> None:
    # Both conditions are present; the critical cap is the one that actually
    # changed the letter (F either way) — the two-high cap made no visible
    # difference of its own to explain.
    findings = [
        _finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED"),
        _finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL"),
        _finding(Severity.HIGH, ModuleName.HEADERS, "HSTS_MISSING"),
    ]
    assert grade_cap_reason(82, findings) == "capped by 1 critical-severity finding"


def test_grade_cap_reason_is_none_when_a_critical_finding_changes_nothing() -> None:
    # The score already bands to F on its own — the critical cap fired, but
    # there is no disagreement between the letter and the score to explain.
    findings = [_finding(Severity.CRITICAL, ModuleName.CERTIFICATE, "CERT_EXPIRED")]
    assert grade_for_score(10) == Grade.F
    assert grade_cap_reason(10, findings) is None


def test_grade_cap_reason_is_none_for_a_single_high_finding() -> None:
    # The two-high cap needs 2+ — one alone never changes the letter.
    findings = [_finding(Severity.HIGH, ModuleName.TLS, "TLS_LEGACY_PROTOCOL")]
    assert grade_cap_reason(75, findings) is None


def test_grade_cap_reason_excludes_domain_expiry_codes_like_the_caps_themselves() -> None:
    # Gate A follow-up A4: these codes are excluded from the caps entirely
    # (grading.py's GRADE_CAP_EXCLUDED_CODES) — the reason must agree.
    findings = [
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_CRITICAL"),
        _finding(Severity.HIGH, ModuleName.DNS, "DOMAIN_EXPIRING_SOON"),
    ]
    assert grade_cap_reason(82, findings) is None
