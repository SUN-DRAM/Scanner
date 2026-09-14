"""docs/urgent_scan_corruption.md Finding 4, Step 1.2: `parse_stored_scan`
must turn a `scans.result` row written under any past contract version back
into a `Scan` without ever raising `ValidationError` — that's the exact
crash that overwrote successful monitored scans back to `failed`.
"""

from __future__ import annotations

from app.enums import ModuleErrorCode, ModuleStatus
from app.scan_compat import (
    CURRENT_SCAN_RESULT_SCHEMA_VERSION,
    parse_stored_scan,
    stamp_schema_version,
)
from tests.pdf_fixtures import default_modules, make_completed_scan


def _pre_v3_payload() -> dict:
    """A row as it would have been written before v3.0 (`is_complete`/
    `incomplete_modules`), v3.1/v3.3 (`grade_cap_reason`), and v3.4
    (structured `ModuleResult.error`) all existed — no `schema_version`
    key, and one module's `error` is a bare string."""
    modules = default_modules()
    modules.tls.status = ModuleStatus.ERROR
    modules.tls.data = None
    modules.tls.score = None
    modules.tls.grade = None
    scan = make_completed_scan(modules=modules)
    payload = scan.model_dump(mode="json")
    payload.pop("is_complete")
    payload.pop("incomplete_modules")
    payload.pop("grade_cap_reason")
    payload["modules"]["tls"]["error"] = "handshake failed: connection reset"
    return payload


def test_parse_stored_scan_defaults_is_complete_true_for_a_pre_v3_row() -> None:
    parsed = parse_stored_scan(_pre_v3_payload())
    assert parsed.is_complete is True
    assert parsed.incomplete_modules == []
    assert parsed.grade_cap_reason is None


def test_parse_stored_scan_normalises_a_bare_string_error_to_structured() -> None:
    parsed = parse_stored_scan(_pre_v3_payload())
    assert parsed.modules.tls is not None
    assert parsed.modules.tls.error is not None
    assert parsed.modules.tls.error.code == ModuleErrorCode.UNEXPECTED_ERROR
    assert parsed.modules.tls.error.message == "handshake failed: connection reset"


def test_parse_stored_scan_does_not_override_real_values_on_a_current_row() -> None:
    """A row already written under the current schema must round-trip
    unchanged — the defaults are for genuinely missing fields only."""
    scan = make_completed_scan(
        is_complete=False,
        incomplete_modules=["certificate"],
        grade_cap_reason="capped by 1 critical-severity finding",
    )
    payload = stamp_schema_version(scan.model_dump(mode="json"))
    parsed = parse_stored_scan(payload)
    assert parsed.is_complete is False
    assert parsed.incomplete_modules == ["certificate"]
    assert parsed.grade_cap_reason == "capped by 1 critical-severity finding"


def test_stamp_schema_version_is_not_part_of_the_parsed_scan() -> None:
    """The version marker is bookkeeping for the stored row, never a `Scan`
    field — it must not leak into an API response."""
    scan = make_completed_scan()
    stamped = stamp_schema_version(scan.model_dump(mode="json"))
    assert stamped["schema_version"] == CURRENT_SCAN_RESULT_SCHEMA_VERSION
    parsed = parse_stored_scan(stamped)
    assert not hasattr(parsed, "schema_version")
    assert "schema_version" not in parsed.model_dump(mode="json")
