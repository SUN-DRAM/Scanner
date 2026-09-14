"""Version-tolerant reading of a stored `scans.result` JSONB payload.

docs/urgent_scan_corruption.md, Finding 4: the contract has moved v1.0 ->
v3.4, and each amendment that added a required `Scan` or `ModuleResult`
field made every row written before it unparseable under the *current*
schema. `Scan.model_validate(record.result)`, called directly against a
historical row, raised into `evaluate_and_fire_alerts` and overwrote an
already-completed, already-graded scan back to `failed`
(app/scanner/orchestrator.py's `_run_and_persist`).

This module is the one place that gap is closed, on read, instead of at
every call site (the scan router, the alert evaluator, and anything else
that ever loads `scans.result`). `parse_stored_scan` must never raise
`pydantic.ValidationError` for a row this application itself wrote, no
matter how old.
"""

from __future__ import annotations

from typing import Any

from app.enums import ModuleErrorCode
from app.schemas import Scan

# Bumped whenever a `Scan`/`ModuleResult` amendment would otherwise break a
# previously-stored row. Stored as a sibling key alongside the dumped `Scan`
# fields, never as a field of `Scan` itself — `ContractModel` has no
# `extra="forbid"`, so this key is silently dropped by `Scan.model_validate`
# and never reaches an API response. Purely an internal bookkeeping aid: it
# lets an audit query (`result->>'schema_version'`) find old rows directly,
# without needing to attempt validation to find out.
CURRENT_SCAN_RESULT_SCHEMA_VERSION = 2

_MODULE_KEYS = (
    "certificate",
    "chain",
    "tls",
    "dns",
    "email_auth",
    "headers",
    "readiness",
)


def stamp_schema_version(result: dict[str, Any]) -> dict[str, Any]:
    """Called at write time, wrapping `scan.model_dump(mode="json")` before
    it's assigned to `ScanRecord.result`."""
    return {"schema_version": CURRENT_SCAN_RESULT_SCHEMA_VERSION, **result}


def parse_stored_scan(data: dict[str, Any]) -> Scan:
    """The one place `scans.result` is turned back into a `Scan`. Defaults
    are applied only when a field is genuinely absent — a row already
    written under the current schema round-trips unchanged."""
    patched = dict(data)

    # v3.0 (docs/FIX_GRADING.md §9 Step 4b): partial-completion tracking
    # didn't exist yet, and a scan was only ever stored once it succeeded —
    # `is_complete: true` is the honest reading of "this row predates the
    # concept," not a guess (CLAUDE.md rule 7 still applies: this is a
    # documented default, not a guessed grade or timestamp).
    patched.setdefault("is_complete", True)
    patched.setdefault("incomplete_modules", [])

    # v3.1/v3.3 (docs/FIX_GRADING.md): the grade-cap override didn't exist
    # yet, so there is nothing to explain.
    patched.setdefault("grade_cap_reason", None)

    modules = patched.get("modules")
    if isinstance(modules, dict):
        patched_modules = dict(modules)
        for key in _MODULE_KEYS:
            module = patched_modules.get(key)
            if not isinstance(module, dict):
                continue
            error = module.get("error")
            # v3.4 (docs/Fix headers and incomplete.md §6.2): `error` was a
            # bare `str(exc)` before structured `ModuleError` existed. The
            # original exception type isn't recoverable from that string, so
            # it's tagged UNEXPECTED_ERROR rather than guessed at — the
            # message itself is preserved verbatim.
            if isinstance(error, str):
                patched_module = dict(module)
                patched_module["error"] = {
                    "code": ModuleErrorCode.UNEXPECTED_ERROR.value,
                    "message": error,
                }
                patched_modules[key] = patched_module
        patched["modules"] = patched_modules

    return Scan.model_validate(patched)
