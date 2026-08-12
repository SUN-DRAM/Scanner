"""Gate A accuracy harness — scans a fixed corpus of real, live hosts and
reports whether the scanner is actually correct, not just non-crashing.

Not part of `pytest` (needs live network to external hosts). Run with:

    docker compose exec api python -m tests.accuracy.run

Exits non-zero if any hard assertion fails: a known-bad host that didn't
produce its expected finding, a known-good host with a high/critical
finding, or any host that raised an unhandled exception during scanning.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.enums import Severity
from app.grading import ModuleScoreInput, grade_scan
from app.scanner import ScanContext
from app.scanner.orchestrator import _modules_as_pairs, _run_all_modules
from app.schemas import Modules
from tests.accuracy.corpus import (
    EDGE_CASES,
    INDIAN_REAL_WORLD_HOSTS,
    KNOWN_BAD_HOSTS,
    KNOWN_GOOD_HOSTS,
    EdgeCase,
)

CONCURRENCY = 6


@dataclass
class ScanOutcome:
    hostname: str
    crashed: bool = False
    crash_detail: str = ""
    modules: Modules | None = None
    findings: list[str] = field(default_factory=list)
    grade: str | None = None
    score: int | None = None
    module_errors: dict[str, str] = field(default_factory=dict)


async def _scan_one(hostname: str, semaphore: asyncio.Semaphore) -> ScanOutcome:
    async with semaphore:
        outcome = ScanOutcome(hostname=hostname)
        try:
            ctx = ScanContext(hostname=hostname, port=443, now=datetime.now(UTC))
            modules = await asyncio.wait_for(_run_all_modules(ctx), timeout=60)
        except Exception as exc:  # noqa: BLE001 - the one place a crash must not propagate
            outcome.crashed = True
            outcome.crash_detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            return outcome

        outcome.modules = modules
        module_inputs = [
            ModuleScoreInput(module=name, status=result.status, findings=result.findings)
            for name, result in _modules_as_pairs(modules)
            if result is not None
        ]
        grading = grade_scan(module_inputs)
        outcome.grade = grading.overall_grade.value
        outcome.score = grading.overall_score
        outcome.findings = [f.code for f in grading.findings]

        for name, result in _modules_as_pairs(modules):
            if result is not None and result.error is not None:
                outcome.module_errors[name.value] = result.error

        return outcome


async def _scan_many(hostnames: list[str]) -> dict[str, ScanOutcome]:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    outcomes = await asyncio.gather(*(_scan_one(h, semaphore) for h in hostnames))
    return dict(zip(hostnames, outcomes, strict=True))


def _print_header(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


async def run_known_bad() -> tuple[int, int]:
    _print_header("KNOWN-BAD CORPUS — every host must produce a finding, never crash")
    hosts = [h.hostname for h in KNOWN_BAD_HOSTS]
    results = await _scan_many(hosts)

    passed = 0
    failed = 0
    for entry in KNOWN_BAD_HOSTS:
        outcome = results[entry.hostname]
        print(f"\n--- {entry.hostname} ---")
        print(f"    note: {entry.note}")
        if outcome.crashed:
            print(f"    CRASH: {outcome.crash_detail}")
            failed += 1
            continue

        print(f"    grade={outcome.grade} score={outcome.score}")
        print(f"    findings: {outcome.findings}")
        if outcome.module_errors:
            print(f"    module errors (status=error): {outcome.module_errors}")

        if entry.expected_code is None:
            print("    RESULT: observed only (no confident a-priori expectation)")
            passed += 1
            continue

        if entry.expected_code in outcome.findings:
            print(f"    RESULT: PASS — {entry.expected_code} present")
            passed += 1
        else:
            print(f"    RESULT: FAIL — expected {entry.expected_code}, not found")
            failed += 1

    return passed, failed


async def run_known_good() -> tuple[int, int]:
    _print_header("KNOWN-GOOD CORPUS — zero high/critical findings")
    results = await _scan_many(list(KNOWN_GOOD_HOSTS))

    passed = 0
    failed = 0
    for hostname in KNOWN_GOOD_HOSTS:
        outcome = results[hostname]
        print(f"\n--- {hostname} ---")
        if outcome.crashed:
            print(f"    CRASH: {outcome.crash_detail}")
            failed += 1
            continue

        high_or_critical = []
        assert outcome.modules is not None
        for _name, result in _modules_as_pairs(outcome.modules):
            if result is None:
                continue
            for finding in result.findings:
                if finding.severity in (Severity.HIGH, Severity.CRITICAL):
                    high_or_critical.append(finding.code)

        print(f"    grade={outcome.grade} score={outcome.score}")
        print(f"    all findings: {outcome.findings}")
        if outcome.module_errors:
            print(f"    module errors (status=error): {outcome.module_errors}")

        if not high_or_critical:
            print("    RESULT: PASS — zero high/critical findings")
            passed += 1
        else:
            print(f"    RESULT: FAIL — high/critical findings present: {high_or_critical}")
            failed += 1

    return passed, failed


async def run_indian_corpus() -> None:
    _print_header("INDIAN REAL-WORLD CORPUS — no assertions, print for review")
    results = await _scan_many(list(INDIAN_REAL_WORLD_HOSTS))

    for hostname in INDIAN_REAL_WORLD_HOSTS:
        outcome = results[hostname]
        print(f"\n--- {hostname} ---")
        if outcome.crashed:
            print(f"    CRASH: {outcome.crash_detail}")
            continue
        print(f"    grade={outcome.grade} score={outcome.score}")
        print(f"    findings ({len(outcome.findings)}): {outcome.findings}")
        if outcome.module_errors:
            print(f"    module errors (status=error): {outcome.module_errors}")
        assert outcome.modules is not None
        cert = outcome.modules.certificate
        if cert is not None and cert.data is not None:
            print(
                f"    certificate: issuer={cert.data.issuer_organization!r} "
                f"lifetime_days={cert.data.lifetime_days} "
                f"days_until_expiry={cert.data.days_until_expiry}"
            )
        readiness = outcome.modules.readiness
        if readiness is not None and readiness.data is not None:
            print(
                f"    readiness: verdict={readiness.data.verdict.value} "
                f"survives_2027={readiness.data.survives_2027}"
            )
        dns = outcome.modules.dns
        if dns is not None and dns.data is not None:
            print(
                f"    dns: registrar={dns.data.registrar!r} "
                f"days_until_domain_expiry={dns.data.days_until_domain_expiry}"
            )


async def run_edge_cases() -> tuple[int, int]:
    _print_header("EDGE CASES — must degrade gracefully, never crash, never invent data")
    hosts = [e.hostname for e in EDGE_CASES]
    # aspmx.l.google.com and example.com repeat across cases with different
    # labels — dedupe the actual network calls.
    unique_hosts = list(dict.fromkeys(hosts))
    results = await _scan_many(unique_hosts)

    passed = 0
    failed = 0
    for case in EDGE_CASES:
        outcome = results[case.hostname]
        print(f"\n--- {case.label} ({case.hostname}) ---")
        print(f"    note: {case.note}")
        if outcome.crashed:
            print(f"    RESULT: FAIL — unhandled exception: {outcome.crash_detail}")
            failed += 1
            continue

        print(f"    grade={outcome.grade} score={outcome.score}")
        print(f"    findings: {outcome.findings}")
        if outcome.module_errors:
            print(f"    module errors (status=error): {outcome.module_errors}")

        assert outcome.modules is not None
        _print_edge_case_detail(case, outcome.modules)
        print("    RESULT: PASS — completed without crashing")
        passed += 1

    return passed, failed


def _print_edge_case_detail(case: EdgeCase, modules: Modules) -> None:
    if case.label == "no_mx_records":
        dns = modules.dns
        if dns is not None and dns.data is not None:
            print(f"    mx_records: {dns.data.mx_records}")
    elif case.label == "no_caa_record":
        dns = modules.dns
        if dns is not None and dns.data is not None:
            print(f"    caa_present: {dns.data.caa_present}, caa_records: {dns.data.caa_records}")
    elif case.label == "wildcard_certificate":
        cert = modules.certificate
        if cert is not None and cert.data is not None:
            print(
                f"    is_wildcard: {cert.data.is_wildcard}, "
                f"subject_alternative_names: {cert.data.subject_alternative_names[:5]}"
            )
    elif case.label == "cloudflare_proxied":
        cert = modules.certificate
        if cert is not None and cert.data is not None:
            print(
                f"    issuer_organization: {cert.data.issuer_organization!r}, "
                f"issuer_common_name: {cert.data.issuer_common_name!r}"
            )
    elif case.label == "whois_privacy_redacted":
        dns = modules.dns
        if dns is not None and dns.data is not None:
            print(
                f"    registrar: {dns.data.registrar!r}, "
                f"domain_expires_at: {dns.data.domain_expires_at!r}, "
                f"days_until_domain_expiry: {dns.data.days_until_domain_expiry!r}"
            )
    elif case.label == "idn_domain":
        cert = modules.certificate
        if cert is not None and cert.data is not None:
            print(f"    hostname_matches: {cert.data.hostname_matches}")


async def main() -> int:
    known_bad_passed, known_bad_failed = await run_known_bad()
    known_good_passed, known_good_failed = await run_known_good()
    await run_indian_corpus()
    edge_passed, edge_failed = await run_edge_cases()

    _print_header("SUMMARY")
    print(f"Known-bad corpus:  {known_bad_passed} passed, {known_bad_failed} failed")
    print(f"Known-good corpus: {known_good_passed} passed, {known_good_failed} failed")
    print(f"Edge cases:        {edge_passed} passed, {edge_failed} failed")
    print(f"Indian corpus:     {len(INDIAN_REAL_WORLD_HOSTS)} scanned, no assertions")

    total_failed = known_bad_failed + known_good_failed + edge_failed
    if total_failed:
        print(f"\n{total_failed} hard assertion(s) failed.")
        return 1
    print("\nAll hard assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
