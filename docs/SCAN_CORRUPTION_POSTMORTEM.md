# Postmortem — scans silently overwritten from completed to failed

**Status:** resolved. **Severity:** customer-facing false alerts sent. **Affected window:** 2026-09-13 09:55 UTC – 2026-09-14 09:15 UTC (~23 hours, until the fix deployed).

## What happened

`evaluate_and_fire_alerts` (`app/alerts.py`), run after every completed monitor-linked scan, loads the monitor's previous completed scan and validates its stored `scans.result` JSON directly against the current `Scan` Pydantic model (`Scan.model_validate(record.result)`). A row written before contract v3.0 has no `is_complete`/`incomplete_modules` keys; a row written before v3.1/v3.3 has no `grade_cap_reason`. Reading either raised `pydantic.ValidationError`.

`app/scanner/orchestrator.py`'s `_run_and_persist` had already committed the *new* scan as `status: "completed"` with its real grade before calling `evaluate_and_fire_alerts` — that commit is not the bug. But the `ValidationError` propagated up through `run_scan`'s outer `except Exception` handler, which called `_mark_failed` on the scan it had just successfully persisted. `_mark_failed` sets `status: "failed"` and replaces `scans.result` with an empty, ungraded shape — but it never touches the `overall_grade`/`overall_score`/`headline` *columns*, which is what left the tell-tale signature: a `failed` scan with a real grade still attached, a state no genuine failure path can produce.

Once four such failures happened for the same monitor with no success in between, `record_scan_failure`'s retry-backoff logic fired a `scan_failure` `AlertEvent` — a false "your site failed to scan" email, for a site that had in fact scanned cleanly.

By the time this was found (an unrelated investigation into public-scan reliability, `docs/Fix scan reliability.md`, happened to grep the worker logs), it had corrupted 20 scans across 6 monitors on 2 orgs and sent 5 false `scan_failure` emails. All 20 corrupted rows were deleted after a verified backup and a reviewed dry run (`docs/urgent_scan_corruption.md` Step 3) — the original per-module data was unrecoverable (`_mark_failed` had already overwritten it), and fresh scheduled re-scans, now running the fixed code, superseded them.

## Why the tests missed it

**No test exercised a stored result written under an older schema.** Every test fixture that builds a `scans.result` payload (`tests/pdf_fixtures.py`'s `make_completed_scan`) is built from the *current* `Scan` model — it round-trips through `model_dump()` and `model_validate()` using the same schema version on both ends by construction. Four separate contract amendments (v3.0, v3.1, v3.3, v3.4) each added a field to `Scan`/`ModuleResult`, and each one silently broke every row already sitting in the production database, invisibly, because nothing in the test suite ever fed an *old-shaped* payload back through the current model.

## Why nothing alerted us

Three customer-visible monitors flipped from a real grade to `failed` on a recurring schedule (every ~2h15, matching the scheduler's retry backoff), and the only reason this surfaced was a human reading raw worker logs for an unrelated question. `GET /api/v1/admin/health` — built specifically so operational problems are found "before a customer does" — had no signal for this at all: `scans_24h.failed` just looked like ordinary failures, indistinguishable from a slow origin or a bad hostname.

## What's now in place

1. **The crash can't corrupt a successful scan anymore.** `orchestrator.py` isolates every post-commit side effect (alert evaluation, monitor bookkeeping) in its own `try`/`except` that logs and moves on — an exception there can never reach `_mark_failed`, because by that point the scan has already succeeded and `_mark_failed` has no business running.

2. **Reading a stored scan is now version-tolerant.** New `app/scan_compat.py` — `parse_stored_scan()` fills in documented defaults for genuinely-missing fields (`is_complete: true` for a pre-v3.0 row, since those scans had no concept of partial completion and were only ever stored on success) instead of validating directly against the current schema. Used at every read of `scans.result` (the scan router, the alert evaluator). `stamp_schema_version()` tags new writes with a `schema_version` marker (storage-only, never part of the public contract shape) so a future audit can find old rows directly instead of needing to trigger a crash to discover they exist.

3. **A shared test fixture for "a row written under an older schema."** `tests/pdf_fixtures.py`'s `as_pre_v3_schema_row()` takes a current, fully-valid dumped `Scan` and strips it back down to the pre-v3.0/v3.1/v3.3/v3.4 shape (optionally including the pre-v3.4 bare-string module `error`). Used by `tests/test_scan_compat.py` (the parser directly), `tests/test_scans_router.py` (the scan router, end to end through a real DB row and the real endpoint), and `tests/test_alerts.py` (`_fetch_previous_completed_scan`, the exact original crash site) — one canonical old-schema payload, not three ad hoc ones. **This class of bug must not be able to return at the next contract amendment without a test catching it first**, and now one will.

4. **`GET /api/v1/admin/health` has a live canary.** New `anomalous_failed_scans_24h` (contract v3.5): `COUNT(*)` over `scans` in the last 24h where `status = 'failed'` and `overall_grade IS NOT NULL` — the exact, only-reachable-this-way signature this incident left behind. Renders as a red banner on `/admin/health`, same treatment as the existing scheduler-overdue alarm, whenever it's non-zero.

## Still open, not part of this fix

`_mark_failed` also calls `increment_daily_stat(..., "scans_failed", ...)` on top of the `scans_completed` increment the original success already recorded, so `daily_stats` double-counted these 20 scans in both buckets for 2026-09-13/14. That table is separate from everything touched here and hasn't been corrected.
