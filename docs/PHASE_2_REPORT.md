# Phase 2 development report

**Date:** 2026-08-18
**Scope:** `docs/PHASE_2_PROMPT.md`, Step 0 through Step 8, in full.
**Contract:** v1.0 → v2.7 (`CONTRACT.md` §14 amendment log).

## Summary

Phase 2 took the product from "a stranger gets a free graded report" to "a stranger becomes a paying customer we watch and alert on a schedule." Nine steps shipped across eleven commits, roughly 12,700 net lines added to the Phase 1 baseline. Every step landed with its own passing test suite, and the contract was amended in lockstep with the code at every step that changed the API surface — never after the fact.

| Step | What shipped | Contract change |
|---|---|---|
| 0 | Production fixes: AWS migration cleanup, SSRF self-block bug, `robots.txt`, DEPLOY.md rewrite | None (infra only) |
| 1 | Contract amendment only — every Phase 2 enum, data shape, and error code, before any code | v1.0 → v2.0 |
| 2 | Email OTP auth, users/orgs/memberships, session cookie, RBAC | v2.0 → v2.1 |
| 3 | Monitored hostnames: CRUD, bulk import, quota enforcement | v2.2 |
| 4 | Scheduler: `SKIP LOCKED` claiming, jitter, concurrency cap, retry backoff | v2.3 |
| 5 | Alert engine: triggers, dedupe, quiet hours, digest mode, delivery | v2.4 |
| 6 | Billing: Razorpay + Stripe, webhooks, invoices, GST fields | v2.5 |
| 7 | Customer dashboard: `/login`, `/app/*`, seven pages | v2.6 |
| 8 | One-off waitlist-to-account migration command | v2.7 (no surface change) |

**Final verification state**, all inside `docker compose exec api`/`web`:

| Check | Result |
|---|---|
| `pytest` | **331 passed**, 38 deselected (network-dependent, per Gate A's `not network` policy) |
| `ruff check .` | clean |
| `mypy app` | clean, 51 source files |
| `pnpm lint` | clean |
| `pnpm build` | succeeds, all 63 routes render |

---

## Step 0 — Production fixes (blocking, closed before Phase 2 proper)

The production host had moved from DigitalOcean to AWS EC2 (`ap-south-1`, Elastic IP `65.2.195.179`) since the last deploy, and the migration had left three things stale:

- **A self-inflicted SSRF false-positive.** The safety denylist blocked our own infrastructure by hostname, which silently caught `sundram.tech` itself once `PUBLIC_BASE_URL`/`CORS_ORIGINS` pointed at the real domain — the product could not scan its own credibility check. Fixed by blocking the public IP literally instead of by hostname, and removing the stale DigitalOcean IP that now belonged to a different AWS customer.
- **`robots.txt` had no exclusions.** A blanket allow with nothing carved out for `/api/`, `/admin/`, or the not-yet-built `/app/` — closed proactively, ahead of Step 7 actually needing it.
- **`docs/DEPLOY.md` described a different provider than the one in production.** Full rewrite against the real AWS shape: Security Groups instead of `ufw`, `/opt/scanner`, the Elastic IP's stop/start survival property, S3 backups via IAM role instead of access keys on disk.

A close-out commit followed with canonical-URL tests, Caddy ACME issuer pinning, and a `scripts/deploy.sh`. No contract change — this step was entirely infrastructure and safety-guard correctness.

## Step 1 — Contract amendment v2.0

Every Phase 2 enum, data shape, error code, and the paginated-list envelope was written into `CONTRACT.md` *before any implementation code*, per rule zero ("contracts are amended by a human, never by a coding session" — this step is the human-reviewed exception where the amendment itself is the deliverable). Four items were proposed pending sign-off rather than assumed: `InvoiceState`'s value set, the `SESSION_SECRET` env var name, the `per_page` pagination ceiling, and the session cookie name. All four were confirmed unchanged in v2.1 — the discipline caught nothing wrong, but the check happened.

## Step 2 — Auth and organisations

Email OTP only, no passwords anywhere in the schema. Six-digit codes via `secrets`, stored only as a salted hash, 10-minute expiry, five verify attempts before burning the code, constant-time comparison. `POST /auth/otp/request` returns an identical `202` whether or not the account exists — never a timing or shape difference that reveals registration status.

`verify_otp` is the one place a `users` row is created, mirroring the "one place" discipline `routers/scans.py` already established for `scans` rows in Phase 1. A brand-new user gets a personal org on the free plan automatically; a user who already exists (return login, or an invite landed first) does not get a second one. Role enforcement (`owner`/`admin`/`member`) lives in one FastAPI dependency (`require_roles`), not scattered through handlers. Cross-org resource ids return `404`, never `403` — confirmed by a dedicated test, since the two look identical to an attacker only if the backend actually enforces it that way everywhere, not just in the endpoints that were top of mind.

## Step 3 — Monitored hostnames

Reused Phase 1's hostname normalisation and SSRF guard exactly — the contract's repeated "no parallel code path" rule enforced literally. `QUOTA_EXCEEDED` returns `{current, limit, plan_code, upgrade_to}` read from `app/plans.py`, never a hardcoded number, so the frontend's upgrade prompt can never drift from the actual plan table. Two scoping decisions were made and documented rather than left implicit: duplicate detection keys on `(hostname, port)` together, not hostname alone; and quota accounting excludes `quota_blocked` monitors, so a monitor doesn't count against the very quota that blocked it.

## Step 4 — Scheduler

`SELECT ... FOR UPDATE SKIP LOCKED` so two workers never claim the same due monitor. `next_scan_at` jittered ±10% so a 500-row bulk import doesn't stampede every six hours forever. A Redis semaphore caps scheduled-scan concurrency at 3, deliberately well under the worker's `max_jobs` of 10 — scheduled scans structurally cannot starve the public scanner, the acquisition channel, since they don't compete for the same budget at all rather than winning a priority contest for it. Failed scans retry at 5m/30m/2h before firing a `scan_failure` alert, reusing the scheduler's own five-minute cadence as the retry mechanism instead of a separate retry job.

## Step 5 — Alert engine

The step the product actually gets paid for. Five trigger types (`cert_expiry`, `domain_expiry`, `grade_regression`, `scan_failure`, `new_critical_finding`), each with a `{monitor_id}:{type}:{threshold}` dedupe key. One interpretation beyond the phase prompt's literal text was made and documented: dedupe gates on a *crossing* check (the current value newly qualifies, the previous scan's didn't), not "still qualifies" — a literal reading would have silently suppressed a genuinely new alert forever after the first one, e.g. after a renewal and a later relapse. Quiet hours (per-org timezone, default `Asia/Kolkata` 21:00–08:00) defer non-urgent alerts to the window's local end; `cert_expiry` at ≤3 days and `scan_failure` always bypass both quiet hours and digest batching, since those are the two cases where "less noisy" would mean "less useful."

## Step 6 — Billing

Razorpay for INR, Stripe for USD, both test mode throughout — no live key ever seen or logged. Webhooks are the actual source of subscription truth: `POST /checkout` never writes a `subscriptions` row itself, only a confirming webhook does, so "webhooks are the source of truth, not the checkout redirect" holds structurally rather than as a stated intention that a bug could quietly violate. A `(provider, event_id)` idempotency ledger (`billing_events`) is checked before touching any subscription/invoice/org row, so a provider's retried webhook can't double-apply a plan change. GST fields (`gstin`, `place_of_supply`) are captured on every invoice now, even with simple rate logic, since retrofitting them later would mean reissuing invoices. `docs/BILLING_TESTING.md` documents the exact test cards and webhook-replay commands for both providers.

## Step 7 — Customer dashboard

`/login`, `/app` (the hostname table — "that column is the product," soonest-expiry-first, server-computed, never re-derived client-side), `/app/monitors/[id]`, `/app/monitors/new`, `/app/alerts`, `/app/billing`, `/app/team`. The result-panel component (`ScanResultBody`) was extracted out of the public share page's `ScanResultView` and reused unchanged in the dashboard — one place the validity bar, findings list, and module cards render, not a fork with its own drift risk. `/app/*` is kept out of search two independent ways that don't fight each other: `robots.ts` disallows the path, and the layout additionally sets `noindex` for any crawler that reads the page anyway (a link-preview bot, one that ignores `robots.txt`).

This step closed three items earlier contract amendments had explicitly deferred rather than invented early: the five alert-preference fields on `PATCH /orgs/current`, the `/alerts/recipients` CRUD endpoints, and `AlertEvent`'s first-ever Pydantic schema (Steps 4 and 5 only ever wrote that table, never serialised it).

## Step 8 — Migrate the waitlist

A one-off command (`app/commands/migrate_waitlist.py`), not an endpoint — the phase prompt specifies a script, so nothing here touches `schemas.py` or `contract.ts`. Per Gate B `waitlist_signups` row: find-or-create the user, create (or, for an email that already has a real account, reuse) a personal free-plan org, add the hostname as a monitor, add the signup email as a recipient, then send the one email promised at signup time. Idempotent by construction — a rerun's `create_monitor` call hits the existing `DUPLICATE_HOSTNAME` guard and skips without resending.

Two existing functions were made public and reusable rather than duplicated, matching the same discipline every other step applied to its own domain: `app/otp.py`'s user/org creation (previously private, used only by OTP verify) and a new `get_or_create_recipient` extracted out of the `/alerts/recipients` router so the migration command and the HTTP endpoint share one insertion path instead of two. Writing this step's tests also surfaced a real gap in `test_scheduler.py`'s cleanup fixture — it deleted stale monitors' child `scans` rows but not `alert_recipients`/`alert_events`, which nothing had ever populated in bulk before this command existed; fixed alongside.

---

## Contract evolution

| Version | Driver |
|---|---|
| v1.0 – v1.5 | Phase 1 (locked before this phase started) |
| v2.0 | Step 1 — every Phase 2 enum, shape, error code, before any code |
| v2.1 | Step 2 — auth/org endpoint shapes; four v2.0 proposals confirmed |
| v2.2 | Step 3 — `/monitors` endpoints, `QUOTA_EXCEEDED` details shape |
| v2.3 | Step 4 — `/monitors/{id}/history`, scheduler behaviour (no new shape) |
| v2.4 | Step 5 — `DigestMode` enum, `Organisation` alert-preference fields, unsubscribe endpoint |
| v2.5 | Step 6 — billing endpoints, `WEBHOOK_INVALID_SIGNATURE`, priced-plan shapes |
| v2.6 | Step 7 — alert-preference `PATCH`, `/alerts/recipients`, `AlertEvent` schema |
| v2.7 | Step 8 — no surface change; documented for the same reason every internal-only step is: so a later session doesn't wonder if it was missed |

Every version bump happened in the same commit as the code it describes, per CLAUDE.md rule 4 (`schemas.py` and `contract.ts` change together) extended to the contract document itself.

## Known follow-ups (not gaps — deliberately out of this session's reach)

- **`RESEND_API_KEY`/`EMAIL_FROM_ADDRESS`, Razorpay/Stripe keys** are unset in this dev environment by design (§4: empty means "not configured, never pretend to work"). OTP codes and alert/migration emails currently log to console (`ConsoleEmailSender`) rather than send. Nothing to fix — just the reason Step 8 hasn't been run against real production data yet.
- **`app.commands.migrate_waitlist` has not been run against production's real `waitlist_signups` table.** It's tested against synthetic rows in this dev DB (`test_step8_migrate_waitlist.py`); running it for real is an operational step, not a code change.
- **A live, logged-in browser walkthrough of `/app` was not completed this session** — the connected Chrome instance couldn't reach this Docker host's `localhost:3000`, an environment boundary, not an app defect. Everything reachable by `curl`/the automated suite (redirects, `robots.txt`, build output for all 63 routes) checked out; a human click-through before shipping is still worth doing.
- **The full Phase 2 acceptance checklist** (`docs/PHASE_2_PROMPT.md`'s closing list — end-to-end signup-to-alert-email, three-scan dedupe verification, quiet-hours deferral proof, cross-org 404s across every resource type, both webhooks' signature/idempotency behaviour under real replay) has been verified piecemeal, per-step, in each step's own test suite, but has not been run as one continuous end-to-end scenario against a real deploy. That's the natural next session.
