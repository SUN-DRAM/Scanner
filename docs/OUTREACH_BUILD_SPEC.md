# Outreach Orchestration Layer — Build Specification v1.1

**Status:** Approved for build.
**Owner:** Sharvesh S
**Repo:** `D:\Scanner` — new module, admin-only
**Depends on:** `CONTRACT.md` v3.4+, the existing scan engine, the PDF renderer, the admin surface

**Changes from v1.0:** hook ranking replaced with the founder's field-tested ranking (§6.2); email template replaced with the founder's sent template (§7.4); daily volume raised to 30 with a warm-up ramp (§9.3); CSV input format specified (§17).

---

## 1. What this is

A pipeline that takes a qualified agency with its client domains and produces a reviewed, ready-to-send outreach email in Gmail drafts, with the right findings cited and the right reports attached.

**It is not a sending machine.** Every email is read by a human before it leaves.

### The target

> Each morning, up to 30 fully-prepared drafts wait in Gmail. Each has the correct hook, correct attachments, correct recipient. You review each in ~5 minutes and send.

That converts ~15 minutes of preparation per agency into ~5 minutes of review.

### The governing principle

**Automate assembly. Never automate judgment or sending.**

This method converts because the email is visibly specific — a real person looked at their actual client sites and found something real. The moment it reads as generated, reply rates collapse and the domain that carries customer alerts starts landing in spam.

---

## 2. Architecture

### 2.1 Separation of concerns

```
SUN-DRAM Scanner       =  security intelligence
Outreach Orchestrator  =  workflow orchestration
```

The orchestrator contains **no security logic**. It never parses a certificate, never decides a severity, never computes a grade. It asks the scanner to scan, reads structured results, assembles artefacts.

### 2.2 Where it lives

Same repo, separate module: `apps/api/app/outreach/`. Admin-only, behind the existing `ADMIN_TOKEN` and `sd_admin` cookie.

It calls the scan engine **directly via function calls**, not over HTTP. Same box, no auth surface, no latency, and it bypasses the public rate limiter (6/hostname/hour) which would otherwise throttle our own batches.

### 2.3 Hard isolation from customer data

Prospect data never touches a customer surface. A prospect scan has no `org_id`, never schedules, never alerts, never appears in a dashboard, never enters `/admin/funnel` metrics.

Reuse `prospect_batches` / `prospect_scans` from migration 0008 where they fit; add the tables in §4 alongside.

---

## 3. The pipeline

```
CSV import
     ↓
Batch scan (paced)
     ↓
Hook selection (deterministic)
     ↓
Draft assembly (template + PDFs + Gmail draft)
     ↓
Human review → send
```

Five stages, each independently re-runnable and idempotent.

---

## 4. Data model

### 4.1 Tables

```sql
outreach_campaigns (
  campaign_id   uuid primary key,
  name          text not null,
  status        varchar(24) not null,      -- draft | running | paused | complete
  created_at    timestamptz not null default now()
)

outreach_prospects (
  prospect_id    uuid primary key,
  campaign_id    uuid not null references outreach_campaigns,
  agency_name    text not null,
  agency_website text,
  contact_name   text,
  contact_email  text not null,
  source         varchar(32),
  icp_grade      varchar(24),
  state          varchar(32) not null,
  state_reason   text,
  do_not_contact boolean not null default false,
  notes          text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (campaign_id, contact_email)
)

outreach_domains (
  domain_id     uuid primary key,
  prospect_id   uuid not null references outreach_prospects on delete cascade,
  hostname      varchar(253) not null,
  relationship  varchar(16) not null default 'client',
  state         varchar(24) not null,
  scan_id       uuid references scans(scan_id),
  scan_attempts integer not null default 0,
  scan_error    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (prospect_id, hostname)
)

outreach_messages (
  message_id         uuid primary key,
  prospect_id        uuid not null references outreach_prospects on delete cascade,
  hook_code          varchar(48) not null,
  hook_domain_id     uuid not null references outreach_domains,
  hook_scan_id       uuid not null references scans(scan_id),
  hook_finding_code  varchar(64),
  secondary_domain_ids uuid[],
  template_variant   smallint not null,
  subject            text not null,
  body               text not null,
  attachment_scan_ids uuid[],
  gmail_draft_id     text,
  gmail_message_id   text,
  state              varchar(24) not null,
  drafted_at         timestamptz,
  sent_at            timestamptz,
  replied_at         timestamptz,
  reply_note         text,
  created_at         timestamptz not null default now(),
  unique (prospect_id)
)

outreach_suppressions (
  email      varchar(320) primary key,
  reason     varchar(32) not null,    -- opted_out | bounced | manual | replied_no
  created_at timestamptz not null default now()
)
```

### 4.2 Findings are referenced, never copied

**No `outreach_findings` table.** Findings already live in `scans.result` as JSONB. A second copy will drift — and stored-shape drift caused the scan corruption bug.

Store the reference (`hook_scan_id` + `hook_finding_code`) and read the finding at draft time through `parse_stored_scan()`, inheriting version tolerance for free.

---

## 5. State machines

### 5.1 Prospect states

```
PENDING            imported, nothing done
SCANNING           domain scans queued or running
ANALYZING          all domains settled, selecting hook
SUPPRESSED         no hook cleared the bar — do not email (§6.3)
DRAFTING           generating PDFs + email + Gmail draft
READY_FOR_REVIEW   draft exists in Gmail, awaiting human
SENT               human sent it
REPLIED            reply detected
FAILED             unrecoverable, with reason
SKIPPED            manually excluded
```

### 5.2 Domain states

```
PENDING
RUNNING
COMPLETED           scan finished, is_complete = true
COMPLETED_PARTIAL   scan finished, is_complete = false
RETRYING
FAILED
```

`COMPLETED_PARTIAL` is re-scanned once after `RETRY_BACKOFF_SECONDS`. If still partial, the domain is **excluded from hook selection and from any attachment.** Citing a finding from an incomplete scan is precisely the credibility risk we spent two weeks eliminating.

### 5.3 Message states

```
DRAFTED → READY_FOR_REVIEW → SENT → REPLIED
   ↑              ↓
   └──────────────┤
                  ↘ DISCARDED
```

`READY_FOR_REVIEW → DRAFTED` is "regenerate" (§11's review UI action) — added v1.1 addendum, human sign-off 2026-09-17, CONTRACT.md §11/§14 v3.7. `SENT` stays reachable only from — and only reaches — `REPLIED`: once sent, regenerating would misrepresent what actually left the building. `unique(prospect_id)` (§4.1) means regenerate updates the existing row rather than inserting a second one. See CONTRACT.md §11 v3.7 for the two caller obligations this implies (delete the old Gmail draft and null `gmail_draft_id` before creating the replacement; bump `template_variant`) and the new `state_reason`/`state_changed_at` columns that back it.

---

## 6. Hook selection — deterministic, no model

### 6.1 Inputs

All `COMPLETED` scans belonging to one prospect. Aggregate across the portfolio — **one email per agency, never one per domain.**

### 6.2 Ranking (field-tested — from 30 manual scans and 10 sent emails)

First match wins.

| Rank | `hook_code` | Condition | Source finding |
|---|---|---|---|
| 1 | `CERT_EXPIRED` | certificate already expired | `CERT_EXPIRED` |
| 2 | `CERT_EXPIRING_30` | certificate expiring ≤ 30 days | `CERT_EXPIRING_CRITICAL`, `CERT_EXPIRING_SOON`, `CERT_EXPIRING_WARN` |
| 3 | `CERT_EXPIRING_60` | certificate expiring 31–60 days | same family |
| 4 | `DOMAIN_EXPIRING_30` | domain registration expiring ≤ 30 days | `DOMAIN_EXPIRING_CRITICAL`, `DOMAIN_EXPIRING_SOON` |
| 5 | `READINESS_MANUAL` | any client domain on manual renewal | `READINESS_MANUAL_2027` |
| 6 | `HTTPS_NOT_ENFORCED` | HTTPS not enforced | `HSTS_MISSING` or `NO_HTTPS_REDIRECT` |
| — | *(no hook)* | → `SUPPRESSED` | |

**Rank 1 is an addition to the founder's list.** An already-expired certificate is the single strongest hook available and must not fall through to rank 2's "expiring" wording, which would read as wrong.

Rank 6 covers both findings because they are the same story to a reader — HTTPS isn't properly enforced — and the sent email used `NO_HTTPS_REDIRECT` in exactly that role.

When several domains match the same rank, pick the one with the fewest days remaining; tie-break on worst grade.

### 6.3 Suppression

**If nothing reaches rank 6, send nothing.** State `SUPPRESSED`, revisit in 60 days. An email to an agency whose clients are all fine makes you a vendor rather than someone helping, and there's one first impression per agency.

> **Note on qualification rate.** `HSTS_MISSING` and `NO_HTTPS_REDIRECT` are common, so rank 6 will qualify most agencies and suppression will rarely fire. That's a deliberate consequence of the founder's ranking, not a bug — but track the split in §12. If rank-6 hooks reply materially worse than ranks 1–5, consider dropping rank 6 to a suppression threshold rather than a hook.

### 6.4 Explainability

The review UI must show **why this hook was chosen** — rank, condition met, domain, finding, and the days figure. If a hook looks wrong you need to see the reasoning, not re-derive it.

### 6.5 Secondary evidence

After the primary hook, collect up to **2 supporting findings from other domains**, each at rank 6 or better, for the bullet list in the email body. Prefer findings of a *different* type to the primary — variety reads as thoroughness.

---

## 7. The email

### 7.1 Templates, not runtime generation

**No model writes the body at runtime.** It could state a finding the scan didn't produce — fatal in a security assessment — and generated cold email has a texture people increasingly recognise.

**Three hand-written variants per `hook_code`**, selected round-robin. Variation matters for spam filtering as well as for how it reads.

Every fact traces to a scan result. Nothing inferred, nothing embellished.

### 7.2 A model may help once, offline

Use a model to help draft the variants. You read them, edit them, freeze them into the codebase. Never at runtime, never per email. Revisit after 50 sends, when replies say what works.

### 7.3 Voice

- **"I", not "we".** One person looked at their sites. That's the appeal.
- Specific subject lines that name the finding and the number.
- Sentence case, plain text, no marketing language, no exclamation marks.
- Never claim to have tested, audited, penetration-tested, or certified anything. This is an external observation.

### 7.4 Template — the founder's sent version, with slots

This is the email actually sent, parameterised. **Four changes are marked; the first is strongly recommended.**

```
Subject: {n} issues on {agency}'s client sites

Hi {first_name},                                          ← CHANGE 1

While looking through {agency}'s client portfolio, I checked a couple
of the sites externally to see what their internet-facing security
posture currently looks like.

A couple of things stood out:

  {domain_1} — {finding_1_summary}
  {domain_2} — {finding_2_summary}

I've attached the SUN-DRAM assessment reports for both.

{march_2027_line}                                         ← CHANGE 2

SUN-DRAM continuously checks internet-facing infrastructure for
certificate expiry, TLS issues and DNS problems, detects changes, and
tells your team when something needs attention — instead of an ops
engineer remembering to check every client site.

Would you like me to run the rest of your client list? I'll send back
a portfolio report — every domain, expiry dates, grades and findings.
No signup, takes me about half an hour.                   ← CHANGE 3

Fifteen minutes on a call would be better, but a two-line reply is
genuinely useful.

Regards,
Sharvesh S
Founder, SUN-DRAM

--
Reply "no thanks" and I won't contact you again.          ← CHANGE 4
```

**CHANGE 1 — `Hi {first_name},` instead of `Greetings,`.** This is the most valuable single change in the email. Everything else works hard to prove the message is specific to them, and a generic greeting undercuts it in the first two words. Where `contact_name` is missing, fall back to `Hi there,` — never `Greetings,`.

**CHANGE 2 — add the March 2027 line, for `READINESS_MANUAL` hooks only:**

> Worth flagging separately: {domain} is on a {lifetime}-day certificate. From 15 March 2027 the maximum drops to 100 days, so anything renewed by hand goes from once a year to four times a year, per domain. For a portfolio your size that's a real amount of unbilled work.

This is the argument only we make, and it reframes the problem from a cost to billable work. Omit it for other hook codes, where it would read as bolted on.

**CHANGE 3 — one question, not two.** The sent version asks both "would this be useful?" and "shall I check the rest?". They compete, and the portfolio offer is much the stronger — it's concrete, free, and low-commitment. Drop the first.

**CHANGE 4 — an explicit opt-out line.** One line, and it both protects deliverability and is the decent thing to do.

**Removed:** the bold product paragraph is now plain text and one sentence shorter. Heavy bold in a first cold email reads as marketing.

### 7.5 Attachments

`MAX_ATTACHMENTS=2`, configurable, default 2 — matching what has been sent.

> **Caution, not a blocker.** Multiple PDF attachments from an unknown sender is a real spam signal, and it compounds at 30/day in a way it doesn't at 1/day. If inbox placement degrades, drop to 1 attachment and link the second domain's live scan result instead. The link is arguably better anyway — current, interactive, and it pulls them onto the site.

Never attach a report from a `COMPLETED_PARTIAL` scan.

---

## 8. Scanning policy

### 8.1 Pacing

We measured a **98% clean-scan rate at 15-second sequential pacing**. That number describes a traffic profile, not a scanner.

```
MAX_CONCURRENT_SCANS=2
SCAN_DELAY_SECONDS=15
MAX_SCAN_RETRIES=2
RETRY_BACKOFF_SECONDS=300
```

All env-configurable. 30 agencies × ~3 domains = ~90 domains, roughly 25 minutes at this profile. Run batches overnight; there is no reason for them to be fast.

If throughput needs raising, **re-run the 50-domain measurement at the new profile** before trusting the output.

### 8.2 The public scanner takes priority

Outreach batches are background work and must never starve interactive public scans — that's the acquisition channel. Use the existing Redis semaphore pattern with a separate, smaller budget than the worker's `max_jobs`.

### 8.3 Retry

Per-domain, never per-agency. A failure on domain 3 does not re-run domains 1 and 2. Record the `ModuleErrorCode` and attempt count.

---

## 9. Sending and deliverability

**Getting this wrong costs the product, not the campaign.**

### 9.1 Separate the sending reputations

`sundram.tech` sends customer certificate alerts. If outreach complaints damage that domain's reputation, **alerts start landing in spam — and a monitoring product whose alerts don't arrive has no product.**

- Transactional alerts: a dedicated subdomain (`mail.sundram.tech`) via Resend
- Outreach: `founder@sundram.tech` via Google Workspace, sent by hand
- **These paths never mix.** No outreach through Resend, ever.

### 9.2 Gmail drafts, never programmatic send

Create drafts via the Gmail API. Store `gmail_draft_id`. You open Gmail, read, edit, send.

It protects alert deliverability, it gives a human gate that catches wrong attachments and wrong names, and real sends from a real Workspace account look like real mail with normal volume, timing and threading.

### 9.3 Volume — 30 drafts/day, with a send ramp

```
DAILY_DRAFT_CAP=30
DAILY_SEND_CAP=<ramped, see below>
```

Drafting 30/day is fine from day one — drafts cost nothing.

**Sending 30/day from day one is not.** The binding constraint here is not review capacity, it's sending reputation. `sundram.tech` is a young domain with little sending history, and a sudden jump to 30 cold emails a day is one of the clearest spam-filter signals there is. Once a domain's reputation is damaged it takes weeks to recover, and it takes your customer alerts down with it.

| Period | `DAILY_SEND_CAP` |
|---|---|
| Week 1 | 10 |
| Week 2 | 20 |
| Week 3 onward | 30 |
| Hard ceiling | 30 |

Enforced in code, not intention. Excess drafts simply queue as `READY_FOR_REVIEW` and carry to the next day — nothing is lost.

Business hours IST, spread through the day, not a burst.

### 9.4 Hygiene

- No tracking pixels, no link shorteners, plain-text signature
- Opt-out line in every email
- `outreach_suppressions` checked before every draft, honoured permanently
- Bounces recorded and suppressed automatically

---

## 10. Idempotency and failure

Before any operation: does this already exist? Yes → reuse. No → perform.

| Operation | Key |
|---|---|
| Prospect creation | `campaign_id + contact_email` |
| Domain processing | `prospect_id + hostname` |
| Message creation | `prospect_id` |
| Gmail draft | `message_id` → stored `gmail_draft_id` |

A crash after scan + PDF + draft must not create a second draft on restart.

Every state transition writes `updated_at`, and on failure a `state_reason`. Nothing fails silently — that lesson is already paid for.

---

## 11. Review UI — `/admin/outreach`

Admin-only, `noindex`, excluded in `robots.ts`.

**`/admin/outreach`** — campaigns: name, prospect count, state breakdown, drafted, sent, replied.

**`/admin/outreach/[campaign_id]`** — prospects: agency, contact, domain count, state, hook code, worst grade, soonest expiry. Filter by state. Default sort: `READY_FOR_REVIEW` first.

**`/admin/outreach/prospects/[prospect_id]`** — the working view. Since review is ~5 minutes and happens 30 times a day, this page is the product:
- Agency and contact
- Every domain with state, grade, key findings
- **The chosen hook and why** — rank, condition, domain, finding, days
- Generated subject and body, editable inline
- Attachments listed, each with a PDF preview link
- Actions: regenerate, change hook manually, mark skipped, open Gmail draft

Keyboard navigation between prospects. At 30 a day, every extra click costs half an hour a week.

**`/admin/outreach/metrics`** — §12.

---

## 12. The measurement that justifies building this

**Reply rate by `hook_code`.**

After 50 sends you'll know whether agencies respond to expiring certificates, the March 2027 deadline, or HTTPS enforcement. That number should shape the next phase of the product, and there's no other way to learn it.

| Metric | Broken down by hook code |
|---|---|
| Drafted | ✓ |
| Sent | ✓ |
| Replied | ✓ |
| Reply rate | ✓ |
| Suppressed (and why) | ✓ |

Also report the **share of prospects qualifying at rank 6 versus ranks 1–5**, per §6.3.

Reply detection: poll the Gmail thread for the stored `gmail_message_id`. Mark `REPLIED`, set `replied_at`, surface at the top of the campaign view. A reply is the most valuable output of this system — it should be impossible to miss.

Target ≥15%. Below 10% means the hooks aren't specific or alarming enough — revisit §6, not §7.

---

## 13. Deliberately not built

- A CRM. Gmail plus a state column covers hundreds of prospects.
- Automated follow-up sequences. One human follow-up after 7 days, drafted the same way.
- Open and click tracking. Hurts deliverability; only replies matter at this volume.
- Scraping or discovery. Already solved elsewhere.
- A/B testing infrastructure. Record `hook_code`, read the replies.
- Automatic sending. Not in v1. Revisit after 100 reviewed sends.

---

## 14. Risks

**Scanning without asking.** Everything is passive, unauthenticated, external — the same traffic any visitor generates, and §10 safety rules forbid more. Defensible, and the email says so plainly.

**DPDP.** You store named individuals' business contact details. Have a lawful basis, a retention limit, a deletion path, and honour opt-outs immediately. You sell compliance evidence; sloppiness here is an unforced error.

**Being wrong in public.** A report citing an incorrect finding damages credibility with exactly the person you wanted to impress. `COMPLETED_PARTIAL` never reaches a draft. No exceptions.

**Volume.** Capped in code per §9.3.

---

## 15. Build order

| # | Stage | Days | Gate |
|---|---|---|---|
| 1 | Schema, migration, CSV import, state machines, idempotency | 1 | Import 50 agencies, states correct |
| 2 | Batch scan at measured pacing, retry, `COMPLETED_PARTIAL` handling | 1 | 150 domains overnight, ≥95% clean |
| 3 | Hook ranking + suppression + explainability | 1 | Hooks match founder's judgment on 20 agencies |
| 4 | Templates (3 variants per hook), PDF attach, Gmail draft creation | 2 | 10 drafts in Gmail, correct in every detail |
| 5 | Review UI, state tracking, reply detection, suppressions | 1 | Full loop end to end |

**Stage 3 gets the most care.** If it picks weak hooks, everything downstream is an efficient machine for producing emails nobody answers.

Contract amendment: outreach tables into §11, admin endpoints into §7 marked internal, bump the log.

---

## 16. Validation against the manual baseline

Before trusting the pipeline, run it over **the same 10 agencies already emailed by hand.**

Compare: does it pick the same hook? Does it cite the same domains? Would the generated email have been acceptable to send?

Disagreements are the most valuable output of this whole build — each one is either a bug in the ranking or a piece of judgment not yet encoded.

---

## 17. Input format — the CSV

### 17.1 Shape

**One row per (agency, client domain).** An agency with three client domains occupies three rows. Agency identity is the `contact_email`.

This handles a variable number of domains per agency without list-in-a-cell parsing.

### 17.2 Columns

| Column | Required | Format | Notes |
|---|---|---|---|
| `agency_name` | **yes** | text | As it should appear in the email. "Decipher Zone Technologies", not "decipher-zone" |
| `contact_email` | **yes** | email | The identity key. Never `info@` or `contact@` |
| `client_domain` | **yes** | hostname | Bare hostname. `example.com`, not `https://example.com/` — but the importer normalises per §7.2 anyway |
| `contact_name` | strongly recommended | text | First name preferred. Drives `Hi {first_name}` — the highest-value personalisation in the email |
| `agency_website` | no | hostname | The agency's own site. Scanned as `relationship = own` |
| `source` | no | enum | `clutch` \| `goodfirms` \| `designrush` \| `sortlist` \| `manifest` \| `linkedin` \| `google` \| `other` |
| `icp_grade` | no | enum | `strong` \| `potential` \| `weak` — rows marked `weak` are imported but not scanned by default |
| `notes` | no | text | Free text, shown in the review UI |

### 17.3 Example

```csv
agency_name,contact_name,contact_email,agency_website,client_domain,source,icp_grade,notes
Decipher Zone Technologies,Rahul,rahul@decipherzone.com,decipherzone.com,letshego.com,clutch,strong,Java shop
Decipher Zone Technologies,Rahul,rahul@decipherzone.com,decipherzone.com,101digital.io,clutch,strong,
Decipher Zone Technologies,Rahul,rahul@decipherzone.com,decipherzone.com,clientthree.com,clutch,strong,
ABC Digital,Priya,priya@abcdigital.in,abcdigital.in,client1.com,goodfirms,potential,
ABC Digital,Priya,priya@abcdigital.in,abcdigital.in,client2.com,goodfirms,potential,
```

### 17.4 Import rules

1. UTF-8, comma-separated, header row required, column order irrelevant.
2. Group rows by `contact_email` into one prospect. If `agency_name` differs across rows sharing an email, take the first and warn.
3. Normalise every `client_domain` through the existing §7.2 hostname normalisation and §10 safety guard. Reject and report anything that fails — never scan an unvalidated host.
4. Deduplicate on `(campaign_id, contact_email)` for prospects and `(prospect_id, hostname)` for domains. **Re-importing the same file must be a no-op.**
5. Check `outreach_suppressions` on import. Suppressed emails are skipped and listed in the import report.
6. Reject and report rows missing any required column.
7. Cap at **500 rows per import**, to keep a mistake small.

### 17.5 Import report

After every import, show:

```
Imported:        47 agencies, 142 client domains
Skipped:          3 agencies (already in this campaign)
Suppressed:       1 agency (opted out 12 Aug)
Rejected rows:    4  (2 invalid hostname, 1 missing contact_email, 1 blocked target)
Warnings:         2  (agency_name differs across rows for the same email)
```

Nothing imports silently. A rejected row that vanishes quietly becomes an agency you think you contacted and didn't.
