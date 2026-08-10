"""End-to-end tests for the orchestration logic (module fan-out + grading),
against every host the phase prompt's acceptance criteria name. These don't
touch the database — persistence needs a live Postgres, exercised via
`docker compose exec api pytest` once Step 6 wires up the DB-backed path.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from app.enums import Grade
from app.grading import ModuleScoreInput, grade_scan
from app.safety import HostnameResolutionError, resolve_and_validate
from app.scanner import ScanContext
from app.scanner.orchestrator import _modules_as_pairs, _run_all_modules

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
