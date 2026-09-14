"""End-to-end tests for the orchestration logic (module fan-out + grading),
against every host the phase prompt's acceptance criteria name. These don't
touch the database — persistence needs a live Postgres, exercised via
`docker compose exec api pytest` once Step 6 wires up the DB-backed path.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.enums import Grade, ModuleErrorCode, ModuleName, ModuleStatus
from app.grading import ModuleScoreInput, grade_scan
from app.safety import HostnameResolutionError, resolve_and_validate
from app.scanner import ScanContext
from app.scanner.orchestrator import _modules_as_pairs, _run_all_modules
from app.schemas import ModuleError, ModuleResult

ACCEPTANCE_HOSTS = (
    "google.com",
    "expired.badssl.com",
    "self-signed.badssl.com",
    "wrong.host.badssl.com",
    "untrusted-root.badssl.com",
)


async def _full_scan(hostname: str, port: int = 443):
    ctx = ScanContext(hostname=hostname, port=port, now=datetime.now(UTC))
    modules = await _run_all_modules(ctx)
    module_inputs = [
        ModuleScoreInput(module=name, status=result.status, findings=result.findings)
        for name, result in _modules_as_pairs(modules)
        if result is not None
    ]
    return modules, grade_scan(module_inputs)


@pytest.mark.asyncio
@pytest.mark.parametrize("hostname", ACCEPTANCE_HOSTS)
async def test_acceptance_hosts_produce_a_complete_non_crashing_scan(
    hostname: str, require_internet: None
) -> None:
    modules, grading = await _full_scan(hostname)
    # Every module ran to some conclusion — none of the seven silently
    # missing — even where the target is deliberately broken.
    for _name, result in _modules_as_pairs(modules):
        assert result is not None
    assert grading.overall_grade in list(Grade)
    assert 0 <= grading.overall_score <= 100
    assert grading.headline


@pytest.mark.asyncio
async def test_broken_certificate_hosts_grade_f(require_internet: None) -> None:
    for hostname in ("expired.badssl.com", "self-signed.badssl.com", "wrong.host.badssl.com"):
        _modules, grading = await _full_scan(hostname)
        assert grading.overall_grade == Grade.F, hostname


@pytest.mark.asyncio
async def test_headers_module_does_not_cascade_fail_from_a_broken_certificate(
    require_internet: None,
) -> None:
    modules, _grading = await _full_scan("self-signed.badssl.com")
    assert modules.headers is not None
    assert modules.headers.error is None
    assert modules.headers.data is not None


@pytest.mark.asyncio
async def test_nonexistent_domain_fails_fast_without_running_any_module(
    require_internet: None,
) -> None:
    hostname = "this-domain-should-not-exist-sundram.invalid"
    started = time.perf_counter()
    with pytest.raises(HostnameResolutionError):
        await resolve_and_validate(hostname)
    # The whole point of the upfront check: this must not wait anywhere near
    # the per-module 8s timeout, let alone all seven of them.
    assert time.perf_counter() - started < 5


@pytest.mark.asyncio
async def test_full_scan_completes_well_under_the_20_second_budget(
    require_internet: None,
) -> None:
    started = time.perf_counter()
    await _full_scan("google.com")
    assert time.perf_counter() - started < 20


@pytest.mark.asyncio
async def test_self_scan_of_sundram_tech_completes_with_no_module_in_error(
    require_internet: None,
) -> None:
    """PDF_FIXES.md Fix 3: our own public marketing site must be scannable,
    and every module must actually complete — a silent partial failure here
    is exactly the "confidently wrong PDF" bug this whole prompt exists to
    catch, and it must show up as a failing test, not a surprise in a
    generated report. If this fails, the cause is host reachability from
    wherever the test runs (a security group / network path issue), not
    `app/safety.py` — §10 rule 8 deliberately exempts a hostname that merely
    *resolves to* our own IP, blocking only that IP submitted literally
    (see `OWN_PUBLIC_IPS`'s own docstring); confirmed directly against this
    hostname, not assumed from reading the code."""
    modules, grading = await _full_scan("sundram.tech")
    errored = [name for name, result in _modules_as_pairs(modules) if result.status == "error"]
    assert errored == [], f"modules reported error: {errored}"
    assert grading.is_complete is True
    assert grading.overall_grade is not None


@pytest.mark.asyncio
async def test_certificate_and_chain_share_one_handshake(require_internet: None) -> None:
    """docs/fix_connection_footprint.md Step 2.1: certificate and chain used
    to each open their own separate handshake for the same host — two
    connections for data that arrives together in one response. Asserts
    the real fetch (`open_pinned_tls_handshake`, wrapped not replaced, so
    this still exercises the real network path) is called exactly once for
    the pair, not twice, while both modules still produce correct,
    independent results."""
    from app import safety

    call_count = 0
    original = safety.open_pinned_tls_handshake

    async def _counting_wrapper(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original(*args, **kwargs)

    with patch("app.scanner.open_pinned_tls_handshake", new=_counting_wrapper):
        modules, _grading = await _full_scan("google.com")

    assert call_count == 1, f"expected one shared handshake fetch, got {call_count}"
    assert modules.certificate is not None
    assert modules.certificate.data is not None
    assert modules.chain is not None
    assert modules.chain.data is not None
    assert modules.chain.data.chain_length >= 2


@pytest.mark.asyncio
async def test_certificate_module_error_nulls_the_overall_grade_end_to_end(
    require_internet: None,
) -> None:
    """PDF_FIXES.md Fix 2: the actual bug shipped as a *scan* — this is the
    full `_run_all_modules` + `grade_scan` pipeline, real network for every
    module except `certificate` (mocked to simulate the error every other
    module here still completes past), proving the fix holds at the level
    a real scan runs at, not only in grading.py's own unit tests."""
    errored_certificate_result: ModuleResult[None] = ModuleResult(
        module=ModuleName.CERTIFICATE,
        status=ModuleStatus.ERROR,
        score=None,
        grade=None,
        label="Certificate",
        summary="This check did not complete — try scanning again.",
        checked_at=datetime.now(UTC),
        duration_ms=10,
        findings=[],
        data=None,
        error=ModuleError(code=ModuleErrorCode.UNEXPECTED_ERROR, message="simulated failure"),
    )

    with patch(
        "app.scanner.orchestrator.certificate.run",
        new=AsyncMock(return_value=errored_certificate_result),
    ):
        modules, grading = await _full_scan("google.com")

    assert modules.certificate is not None
    assert modules.certificate.status == ModuleStatus.ERROR
    # readiness depends on certificate's own result — it must not synthesise
    # a pass just because the mocked error left it with zero findings.
    assert modules.readiness is not None
    assert modules.readiness.status == ModuleStatus.SKIPPED
    assert modules.readiness.grade is None
    assert modules.readiness.score is None

    assert grading.overall_grade is None
    assert grading.overall_score is None
    assert grading.is_complete is False
    assert ModuleName.CERTIFICATE in grading.incomplete_modules
    assert "could not be completed" in grading.headline.lower()
