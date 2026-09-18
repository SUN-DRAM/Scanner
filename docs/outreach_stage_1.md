# Outreach Orchestrator — Stage 1 Prompt

> Paste into a fresh Claude Code session in `D:\Scanner`. `CLAUDE.md` and `CONTRACT.md` are auto-loaded and binding.

---

You are building **Stage 1** of the Outreach Orchestration Layer. Read `docs/OUTREACH_BUILD_SPEC.md` in full before writing anything — it is the specification and it governs this work the way `CONTRACT.md` governs the product.

The usual working agreement applies: the contract wins, complete files only, one step at a time, stop and wait after each step, and flag a `CONTRACT GAP` rather than inventing anything.

## Stage 1 scope

Schema, migration, CSV import, both state machines, and idempotency. **Nothing else.**

Explicitly out of scope, and I will reject it: scanning, hook selection, templates, PDF generation, Gmail integration, the review UI beyond a bare list to verify the import worked. Those are stages 2–5.

The gate for this stage: **import 50 agencies from a CSV, with correct states, and re-importing the same file changes nothing.**

---

## Step 1 — Contract amendment

Before any code. Show me the diff and wait.

- Add the five tables from spec §4.1 to `CONTRACT.md` §11: `outreach_campaigns`, `outreach_prospects`, `outreach_domains`, `outreach_messages`, `outreach_suppressions`.
- Add the three state enums from §5 to §5 of the contract: `OutreachProspectState`, `OutreachDomainState`, `OutreachMessageState`. Closed sets, mirrored in `enums.py` and `contract.ts` in the same edit per rule 4.
- Add the admin endpoints for this stage to §7, marked clearly as internal.
- Add the Stage 1 env vars to §4 (the rest arrive with their stages):
  ```
  OUTREACH_MAX_IMPORT_ROWS=500
  ```
- Bump the amendment log.

Note in the amendment that `outreach_messages` is defined now but unused until Stage 4 — so a later session doesn't think it was missed.

---

## Step 2 — Models and migration

- SQLAlchemy models for all five tables, exactly as §4.1.
- One Alembic migration. Verify it applies cleanly to an empty database **and** to a copy of the current production schema.
- Foreign keys: `outreach_domains` and `outreach_messages` cascade from `outreach_prospects`. `scan_id` references `scans(scan_id)` — **and check the delete behaviour carefully.** We have been bitten twice by the `scans` ↔ `monitored_hostnames` FK cycle. Do not create a third cycle. If deleting a scan would block deleting a prospect, use `ON DELETE SET NULL` and say so.
- Unique constraints per §4.1 — they are the idempotency mechanism, not decoration.
- Indexes on `(campaign_id, state)` and `(prospect_id, state)`; those drive the review UI's default filters.

**No `outreach_findings` table.** Findings are referenced, never copied — see §4.2.

---

## Step 3 — CSV import

Implement §17 exactly.

- Parser: UTF-8, comma-separated, header row required, **column order irrelevant** — map by header name.
- Group rows by `contact_email` into one prospect. If `agency_name` differs across rows sharing an email, take the first and record a warning.
- **Every `client_domain` and `agency_website` goes through the existing §7.2 hostname normalisation and the §10 safety guard.** Reuse those functions directly — no parallel code path, no exceptions. A hostname that fails validation is rejected and reported, never stored and never scanned later.
- Check `outreach_suppressions` at import. Suppressed emails are skipped and listed.
- Reject rows missing any required column, with the row number and the reason.
- Cap at `OUTREACH_MAX_IMPORT_ROWS`.
- Return the import report from §17.5 — imported, skipped, suppressed, rejected with reasons, warnings.

**Idempotency is the point of this step.** Importing the same file twice must produce zero new rows and zero errors. Write the test that proves it: import, count, import again, count, assert equal.

Prospects land in `PENDING`; domains land in `PENDING`.

---

## Step 4 — State machine

A single module owning every transition — not state strings assigned ad hoc across the codebase.

- The three enums from §5, as closed sets.
- One transition function that validates the move is legal, writes `updated_at`, and on any failure writes `state_reason`.
- **Illegal transitions raise.** `SENT` → `PENDING` is a bug, and I want it to surface loudly rather than silently corrupt a campaign.
- Every transition logs, with the prospect or domain id.

Tests: each legal transition, a representative illegal one, and that `state_reason` is populated on every failure path.

This module is the spine of stages 2 through 5. Getting it right now saves rework three times over.

---

## Step 5 — Minimal admin surface

Only enough to verify the import. Not the review UI — that's Stage 5.

- `POST /api/v1/admin/outreach/campaigns` — create a campaign
- `POST /api/v1/admin/outreach/campaigns/{campaign_id}/import` — CSV upload, returns the §17.5 report
- `GET /api/v1/admin/outreach/campaigns` — list with state counts
- `GET /api/v1/admin/outreach/campaigns/{campaign_id}/prospects` — paginated, filterable by state

Behind the existing `ADMIN_TOKEN` / `sd_admin` cookie. Reuse the admin auth dependency; do not write a second one.

One page at `/admin/outreach` — campaign list, a file upload, and the import report rendered plainly. Monochrome, matching the existing admin pages. `noindex`, and `/admin/` is already disallowed in `robots.ts`.

---

## Verification

- Migration applies to an empty DB and to a production-schema copy
- A 50-agency / 150-domain CSV imports with correct counts and states
- **Re-importing the same file changes nothing** — proven by a test, not by inspection
- A malformed CSV produces a useful report rather than a stack trace: bad hostname, missing column, suppressed email, duplicate row
- A hostname that fails the §10 safety guard is rejected at import, not stored
- Illegal state transitions raise
- Full suite green, ruff, mypy, lint, build all clean
- No prospect data appears anywhere in a customer-facing surface — check `/admin/funnel` counts specifically, since prospect scans must never inflate them

---

## Start

Step 1 only. Show me the contract diff and flag anything in the spec you think is wrong or will cause trouble later. I would much rather fix the spec now than discover the problem at Stage 4.