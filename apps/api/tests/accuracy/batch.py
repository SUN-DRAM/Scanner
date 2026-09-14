"""docs/next step measures.md Step 3 — the decisive 50-domain clean-scan-rate
measurement. Not part of `pytest` (needs live network to 50 real external
hosts and runs for well over an hour). Paced realistically ("a few per
minute, not 50 at once" — the doc's own words) rather than fired as a
burst, and run twice, one hour apart, to also measure result stability.

Run (dev container, which ships tests/ — production images don't; see
docs/next step measures.md Step 3 for the production-run alternative):

    docker compose exec api python -m tests.accuracy.batch

Prints a full report to stdout and writes the same data as JSON to
/tmp/step3_batch_pass1.json and /tmp/step3_batch_pass2.json so a future
run can diff against it without re-parsing printed text.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.enums import ModuleName, ModuleStatus
from app.safety import resolve_and_validate
from app.scanner import ScanContext, certificate, chain, headers, tls
from app.scanner.orchestrator import _modules_as_pairs, _run_all_modules
from app.schemas import ModuleResult, Modules
from tests.accuracy.portfolio_corpus import PORTFOLIO_CORPUS

# ~4 scan starts per minute — realistic bulk-prospect-scan pacing, not a
# burst of 50 concurrent connections to 50 different hosts.
PACE_SECONDS = 15.0
SCAN_TIMEOUT_SECONDS = 60.0
# The doc's own ask: re-run the same corpus an hour later and report how
# many results changed. Set PASS_GAP_SECONDS=0 via env for a manual
# two-invocation workflow instead of one long-running process.
PASS_GAP_SECONDS = 3600.0
RETRY_BACKOFF_SECONDS = 2.0

_MODULE_RUNNERS: dict[ModuleName, Callable[[ScanContext], Awaitable[ModuleResult[Any]]]] = {
    ModuleName.CERTIFICATE: certificate.run,
    ModuleName.CHAIN: chain.run,
    ModuleName.TLS: tls.run,
    ModuleName.HEADERS: headers.run,
}

_ASN_CACHE: dict[str, str] = {}


@dataclass
class ScanOutcome:
    hostname: str
    crashed: bool = False
    crash_detail: str = ""
    modules: Modules | None = None
    duration_s: float = 0.0
    resolved_ip: str | None = None
    errored_modules: list[str] = field(default_factory=list)
    module_error_codes: dict[str, str] = field(default_factory=dict)
    retry_rescued: dict[str, bool] = field(default_factory=dict)

    @property
    def all_complete(self) -> bool:
        return not self.crashed and not self.errored_modules

    def to_json(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "crashed": self.crashed,
            "crash_detail": self.crash_detail,
            "duration_s": round(self.duration_s, 3),
            "resolved_ip": self.resolved_ip,
            "errored_modules": self.errored_modules,
            "module_error_codes": self.module_error_codes,
            "retry_rescued": self.retry_rescued,
            "all_complete": self.all_complete,
        }


async def _scan_one(hostname: str) -> ScanOutcome:
    outcome = ScanOutcome(hostname=hostname)
    started = time.monotonic()
    try:
        target = await resolve_and_validate(hostname)
        outcome.resolved_ip = target.ip
    except Exception:  # noqa: BLE001 - resolution failure is reported via the scan itself
        pass

    try:
        ctx = ScanContext(hostname=hostname, port=443, now=datetime.now(UTC))
        modules = await asyncio.wait_for(_run_all_modules(ctx), timeout=SCAN_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - a crash here is itself the finding
        outcome.crashed = True
        outcome.crash_detail = f"{type(exc).__name__}: {exc}"
        outcome.duration_s = time.monotonic() - started
        return outcome

    outcome.modules = modules
    outcome.duration_s = time.monotonic() - started
    for name, result in _modules_as_pairs(modules):
        if result is not None and result.status == ModuleStatus.ERROR:
            outcome.errored_modules.append(name.value)
            if result.error is not None:
                outcome.module_error_codes[name.value] = result.error.code.value
    return outcome


async def _simulate_single_retry(outcome: ScanOutcome) -> None:
    """docs/next step measures.md Step 3's last row: how many failures a
    single retry would have rescued, sizing Step 4.1 before building it."""
    ctx = ScanContext(hostname=outcome.hostname, port=443, now=datetime.now(UTC))
    for module_name in outcome.errored_modules:
        name = ModuleName(module_name)
        runner = _MODULE_RUNNERS.get(name)
        if runner is None:
            continue
        await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        try:
            retry_result = await asyncio.wait_for(runner(ctx), timeout=SCAN_TIMEOUT_SECONDS)
            outcome.retry_rescued[module_name] = retry_result.status != ModuleStatus.ERROR
        except Exception:  # noqa: BLE001 - retry itself failing counts as "not rescued"
            outcome.retry_rescued[module_name] = False


async def _run_pass(label: str) -> list[ScanOutcome]:
    n = len(PORTFOLIO_CORPUS)
    print(f"\n{'=' * 78}\n{label} — {n} hosts, {PACE_SECONDS:g}s apart\n{'=' * 78}")
    tasks: list[asyncio.Task[ScanOutcome]] = []
    for i, host in enumerate(PORTFOLIO_CORPUS):
        if i > 0:
            await asyncio.sleep(PACE_SECONDS)
        print(f"  [{i + 1}/{len(PORTFOLIO_CORPUS)}] starting {host.hostname}")
        tasks.append(asyncio.create_task(_scan_one(host.hostname)))
    outcomes = await asyncio.gather(*tasks)

    print(f"\n  retrying errored modules once, {RETRY_BACKOFF_SECONDS:g}s backoff...")
    for outcome in outcomes:
        if outcome.errored_modules:
            await _simulate_single_retry(outcome)

    return list(outcomes)


async def _asn_for_ip(ip: str) -> str:
    if ip in _ASN_CACHE:
        return _ASN_CACHE[ip]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"https://ipinfo.io/{ip}/org")
            org = resp.text.strip() or "unknown"
    except Exception:  # noqa: BLE001 - ASN lookup is informational, never fatal
        org = "lookup_failed"
    _ASN_CACHE[ip] = org
    return org


async def _report(outcomes: list[ScanOutcome]) -> None:
    total = len(outcomes)
    clean = sum(1 for o in outcomes if o.all_complete)
    with_error = total - clean

    print(f"\n{'-' * 78}\nRESULTS\n{'-' * 78}")
    print(f"Total scanned:              {total}")
    print(f"All 7 modules complete:     {clean} ({100 * clean / total:.1f}%)")
    print(f"At least 1 module errored:  {with_error} ({100 * with_error / total:.1f}%)")

    code_counts: Counter[str] = Counter()
    module_fail_counts: Counter[str] = Counter()
    for o in outcomes:
        for mod, code in o.module_error_codes.items():
            code_counts[code] += 1
            module_fail_counts[mod] += 1
        for mod in o.errored_modules:
            if mod not in o.module_error_codes:
                module_fail_counts[mod] += 1

    print("\nBreakdown by ModuleErrorCode:")
    for code, count in code_counts.most_common():
        print(f"  {code:<24} {count}")

    print("\nWhich modules fail most:")
    for mod, count in module_fail_counts.most_common():
        print(f"  {mod:<16} {count}")

    print("\nFailures clustered by ASN/org:")
    ips = sorted({o.resolved_ip for o in outcomes if o.resolved_ip is not None})
    asn_by_ip: dict[str, str] = {}
    for ip in ips:
        asn_by_ip[ip] = await _asn_for_ip(ip)
        await asyncio.sleep(0.3)  # don't hammer ipinfo.io
    asn_failure_counts: defaultdict[str, list[str]] = defaultdict(list)
    for o in outcomes:
        if o.resolved_ip is None:
            continue
        asn = asn_by_ip.get(o.resolved_ip, "unknown")
        if not o.all_complete:
            asn_failure_counts[asn].append(o.hostname)
    if asn_failure_counts:
        for asn, hosts in sorted(asn_failure_counts.items(), key=lambda kv: -len(kv[1])):
            print(f"  {asn:<40} {len(hosts)} failing: {hosts}")
    else:
        print("  (no failures to cluster)")

    durations = [o.duration_s for o in outcomes if not o.crashed]
    if durations:
        durations_sorted = sorted(durations)
        median = statistics.median(durations_sorted)
        p95_index = min(len(durations_sorted) - 1, int(round(0.95 * (len(durations_sorted) - 1))))
        p95 = durations_sorted[p95_index]
        print(f"\nDuration: median={median:.2f}s p95={p95:.2f}s (contract §13 wants <20s)")

    retried = [o for o in outcomes if o.retry_rescued]
    if retried:
        total_retried_modules = sum(len(o.retry_rescued) for o in retried)
        rescued = sum(1 for o in retried for v in o.retry_rescued.values() if v)
        print(
            f"\nRetry simulation: {rescued}/{total_retried_modules} errored modules "
            f"would have been rescued by one retry ({100 * rescued / total_retried_modules:.1f}%)"
        )

    print("\nPer-host detail:")
    for o in outcomes:
        status = "CLEAN" if o.all_complete else f"ERRORED: {o.errored_modules}"
        crash = f" CRASHED: {o.crash_detail}" if o.crashed else ""
        print(f"  {o.hostname:<28} {o.duration_s:>6.2f}s  {status}{crash}")


def _compare_passes(pass1: list[ScanOutcome], pass2: list[ScanOutcome]) -> None:
    print(f"\n{'=' * 78}\nSTABILITY — same corpus, one hour apart\n{'=' * 78}")
    by_host_1 = {o.hostname: o for o in pass1}
    by_host_2 = {o.hostname: o for o in pass2}
    changed = []
    for hostname in by_host_1:
        o1, o2 = by_host_1[hostname], by_host_2.get(hostname)
        if o2 is None:
            continue
        if o1.all_complete != o2.all_complete or set(o1.errored_modules) != set(o2.errored_modules):
            changed.append((hostname, o1.errored_modules, o2.errored_modules))

    print(f"Hosts with a different outcome between passes: {len(changed)}/{len(by_host_1)}")
    for hostname, before, after in changed:
        print(f"  {hostname:<28} pass1_errors={before}  pass2_errors={after}")


async def main() -> None:
    pass1 = await _run_pass("PASS 1")
    await _report(pass1)

    with open("/tmp/step3_batch_pass1.json", "w") as f:
        json.dump([o.to_json() for o in pass1], f, indent=2)

    print(f"\nWaiting {PASS_GAP_SECONDS / 60:.0f} minutes before pass 2...")
    await asyncio.sleep(PASS_GAP_SECONDS)

    pass2 = await _run_pass("PASS 2 (one hour later)")
    await _report(pass2)

    with open("/tmp/step3_batch_pass2.json", "w") as f:
        json.dump([o.to_json() for o in pass2], f, indent=2)

    _compare_passes(pass1, pass2)
    print("\nFull results written to /tmp/step3_batch_pass1.json and pass2.json")


if __name__ == "__main__":
    asyncio.run(main())
