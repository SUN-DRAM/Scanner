# URGENT — Finding 4: successful scans being overwritten as failed

Do this before anything else in `FIX_SCAN_RELIABILITY.md`. It is corrupting real customer data on a nightly schedule and may have sent false alerts.

Work in this order. Stop after step 1.

---

## Step 1 — Stop the bleeding (do this first, ship it alone)

Two changes, both small:

**1.1 — A post-success step must never be able to mark a scan failed.** `orchestrator.py` commits the scan as `completed` at line ~283, then calls `evaluate_and_fire_alerts` at ~304. When that call raises, the outer handler calls `_mark_failed` and overwrites a good result.

Alerting is a *consequence* of a successful scan, not part of producing one. Narrow the failure handling so anything after the scan is persisted logs its exception and leaves the scan alone. `_mark_failed` should only be reachable from failures in scanning itself.

Audit every other call site that runs after the commit for the same shape.

**1.2 — Make reading stored scans version-tolerant.** This is the actual root cause and it will recur.

We store the full `Scan` object as JSONB and validate it against the *current* schema on read. The contract has gone v1.0 → v3.4, and every amendment adding a required field breaks every row written before it. `is_complete`, `incomplete_modules` and `grade_cap_reason` are simply the first ones to bite.

Fix it properly:
- Add a `schema_version` field to the stored result, set on write.
- On read, parse tolerantly — missing fields take explicit, documented defaults (`is_complete: true` for pre-v3.0 rows is the honest default, since those scans had no concept of partial completion and were only stored when they succeeded).
- Never let a historical row raise a `ValidationError` into a live code path.

Add a test that constructs a pre-v3.0 result payload, stores it, and asserts every read path handles it — the scan router, the alert evaluator, the PDF renderer, the dashboard, and the admin detail page. **This class of bug must not be able to return at v3.5.**

Deploy 1.1 and 1.2 before moving on. The nightly batch runs at 02:45.

---

## Step 2 — Find every victim and assess the damage

**2.1 — Enumerate.** Query for every scan that looks like this corruption rather than a real failure: `status = 'failed'` with a populated `result` containing a valid grade, or `error_code` matching whatever `_mark_failed` wrote for this path. Report the count, the date range, and how many belong to monitored hostnames versus public scans.

**2.2 — Check whether we lied to customers.** Query `alert_events` for `scan_failure` alerts in the affected window and cross-reference against the corrupted scans. For any that were actually `sent`, I need to know: which organisation, which hostname, and when.

**If we told a customer their site failed to scan when it hadn't, we tell them.** A short, plain email: what happened, that their site was fine, that it's fixed. Draft it and show me. This is a monitoring product — a false alarm is a product failure, and quietly fixing the database isn't good enough.

**2.3 — Check for the inverse.** Confirm no scan went the other way: marked successful when it wasn't. Less likely given the mechanism, but this is grade data and I want it verified rather than assumed.

---

## Step 3 — Repair

**Back up the database first.** `./scripts/backup.sh`, verified, before any write.

Then restore the corrupted rows: `status` back to `completed`, with the grade, score and headline from the stored `result`. Do not recompute — the result is intact, only the status column was overwritten.

Run it as a **dry-run first**, printing exactly what it would change, and show me that output before it touches anything. Report affected monitors so their grade history is correct again.

---

## Step 4 — How this shipped

Write a short note in `docs/` covering what happened and why the tests missed it. Two things I want understood:

- **No test exercised a stored result written under an older schema.** Every test fixture is built with the current models, so the incompatibility was invisible.
- **Nothing alerted us.** Three customer hostnames flipped to failed on a schedule and we found out only because an unrelated investigation looked at the logs. `/admin/health` should surface this — a scan transitioning from `completed` to `failed`, or a spike in failed scans, is exactly the signal that page exists for.

Add both: a test fixture representing an older schema version, and an admin health check for anomalous failure rates.

---

## Then, and only then

Return to `FIX_SCAN_RELIABILITY.md`.

Its picture has improved considerably — `healthpowermedical.com` is a genuinely broken origin that we report honestly, and `irctc.co.in` never reached our backend at all. Only `bytemotion.com` is a real source-IP reputation problem, and that's a narrow case rather than a systemic one.

So step 2's pacing work is worth doing but no longer urgent. **Step 3 — the 50-domain measurement — still matters**, because we need the real clean-scan rate before outreach scales, and four anecdotes aren't it.

Send me the Caddy/web access log grep for `irctc.co.in` when convenient. If the request never arrived, something rejected it before our API and I want to know what.