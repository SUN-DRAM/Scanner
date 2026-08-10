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
    grade_for_score,
    grade_module,
    grade_scan,
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
