# Outreach Orchestrator — Stage 2 Prompt

> Paste into a fresh Claude Code session in `D:\Scanner`. `CLAUDE.md` and `CONTRACT.md` (v3.8) are auto-loaded and binding. `docs/OUTREACH_BUILD_SPEC.md` is the specification.

---

You are building **Stage 2** of the Outreach Orchestration Layer: batch scanning.

Stage 1 shipped the schema, CSV import, both state machines and the minimal admin surface. Stage 2 takes imported domains from `PENDING` to a settled state with a real scan attached.

Working agreement as always: contract wins, complete files, one step at a time, stop and wait, flag a `CONTRACT GAP` rather than inventing.

## Scope

Batch scanning at the measured pacing, per-domain retry, `COMPLETED_PARTIAL` handling, and enough progress visibility to watch a batch run.

**Out of scope, and I will reject it:** hook selection, templates, PDF generation, Gmail. Stages 3–5.

**The gate:** 150 domains scanned overnight with ≥95% reaching `COMPLETED`, no scan stuck in `RUNNING`, and a crash mid-batch losing nothing.

---

## Step 1 — Contract amendment

Before code. Show me the diff and wait.

Add the Stage 2 env vars to §4:

```
OUTREACH_MAX_CONCURRENT_SCANS=2
OUTREACH_SCAN_DELAY_SECONDS=15
OUTREACH_MAX_SCAN_RETRIES=2
OUTREACH_RETRY_BACKOFF_SECONDS=300
```

Add the batch-control endpoints to §7 as internal. Bump the log.

---

## Step 2 — The scan runner

A worker job that walks a campaign's `PENDING` domains and scans them.

**Call the scan engine directly**, as the orchestrator already does internally — not over HTTP. Same box, no auth surface, and it bypasses the public rate limiter (6/hostname/hour) which would otherwise throttle our own batch.

**Pacing is the part that matters.** We measured a 98% clean-scan rate at 15-second sequential pacing, and that number describes a traffic profile, not a scanner. Start exactly there: concurrency 2, 15 seconds between scans, both from the env vars above. 150 domains takes about 40 minutes. There is no reason for it to be fast.

**The public scanner takes priority.** Outreach batches are background work and must never starve interactive public scans — that's the acquisition channel. Use the existing Redis semaphore pattern with its own budget, separate from and smaller than the worker's `max_jobs`, exactly as scheduled monitor scans already do.

**Resumability.** A worker restart mid-batch must lose nothing. Claim domains one at a time with `SELECT ... FOR UPDATE SKIP LOCKED` — the same mechanism the monitor scheduler uses — so two workers never claim the same domain and a crash leaves the rest untouched.

**Idempotency.** A domain already in `COMPLETED` is never re-scanned by a batch run. Re-running a batch picks up only `PENDING`, `RETRYING`, and `COMPLETED_PARTIAL` domains eligible for their retry.

**Respect campaign status.** A campaign in `paused` enqueues nothing and claims nothing. This is the column's one real job — make sure it works, because you'll reach for it during an incident.

**Skip `icp_grade = 'weak'` by default**, with an override flag on the batch-start endpoint. No reason to spend scans on prospects already judged poor.

---

## Step 3 — Outcomes and retry

Every scan settles into exactly one state, through the Stage 1 state machine module. No state strings assigned ad hoc.

| Scan outcome | Domain state |
|---|---|
| completed, `is_complete: true` | `COMPLETED` |
| completed, `is_complete: false` | `COMPLETED_PARTIAL` |
| scan failed | `RETRYING`, then `FAILED` when retries are exhausted |

**Retry is per-domain, never per-agency.** A failure on domain 3 does not re-run domains 1 and 2. Record `scan_attempts`, and put the `ModuleErrorCode` or failure reason in `scan_error` — we spent real effort making module errors structured and diagnosable, so use them here rather than storing a bare string.

**`COMPLETED_PARTIAL` gets one re-scan** after `OUTREACH_RETRY_BACKOFF_SECONDS`. If it is still partial, it stays `COMPLETED_PARTIAL` permanently. That state is not a failure — it means we have a result but not a trustworthy one.

Per spec §5.2, a `COMPLETED_PARTIAL` domain is **excluded from hook selection and from any attachment** in Stage 3. Nothing enforces that yet, but write the query helper now — `completed_domains_for_prospect()` — so Stage 3 can't accidentally reach past it.

---

## Step 4 — Prospect roll-up

When every domain for a prospect has settled, move the prospect.

```
SCANNING → ANALYZING        at least one domain COMPLETED
SCANNING → FAILED           no domain reached COMPLETED, with the reason
```

A prospect with two `COMPLETED` and one `FAILED` domain is `ANALYZING` — we can still write a good email from two. Only a total absence of usable scans is a failure.

`ANALYZING` is where Stage 3 picks up.

---

## Step 5 — Batch control and visibility

Endpoints, admin-gated, reusing `require_admin_token`:

- `POST /api/v1/admin/outreach/campaigns/{campaign_id}/scan` — start or resume a batch; optional `include_weak`
- `POST /api/v1/admin/outreach/campaigns/{campaign_id}/pause` and `/resume`
- `GET /api/v1/admin/outreach/campaigns/{campaign_id}/scan-progress` — counts by domain state, in-flight count, estimated completion, and the last 20 settled domains with their outcome

On the campaign page: a **Start scan** button, live progress by state, and the recent-outcome list. Poll the progress endpoint; no websockets.

A batch running for hours needs to be watchable without SSH. That has been a recurring cost on this project — the corruption bug ran nightly for days before anyone noticed.

---

## Step 6 — Measure the batch

At the end of every batch, record and display:

- Clean rate: `COMPLETED / total`
- `COMPLETED_PARTIAL` count and which modules failed, by `ModuleErrorCode`
- `FAILED` count with reasons
- Median and p95 scan duration
- Total wall time
- How many retries rescued a domain that first failed

This is the same measurement discipline as the 50-domain run, applied continuously. If the clean rate drifts below 95% on a real batch, I want to see it on the page rather than discover it when a draft cites nothing.

---

## Verification

- 150 domains scanned end to end, ≥95% `COMPLETED`
- No domain left in `RUNNING` after the batch settles
- Kill the worker mid-batch and restart: nothing lost, nothing double-scanned
- Re-running a finished batch scans nothing
- A paused campaign claims nothing
- A `COMPLETED_PARTIAL` domain is re-scanned exactly once, then left alone
- A prospect with a mix of completed and failed domains lands in `ANALYZING`
- **`/admin/funnel` counts are unchanged by a batch** — prospect scans must never inflate the anonymous-scan metric. Check this specifically, with before-and-after numbers.
- Interactive public scans stay responsive while a batch runs — scan one yourself from a browser during the batch and confirm it completes normally
- Full suite green; ruff, mypy, lint, build clean

---

## Start

Step 1 only. Show me the contract diff, and flag anything in the spec that looks wrong or will hurt at Stage 3.