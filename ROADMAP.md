# SUN-DRAM Scanner — Build Roadmap

Six phases, sequenced by speed-to-first-rupee rather than engineering elegance. Each phase ships something sellable. Nothing depends on a later phase to be useful.

Timings assume AI-assisted development with one person driving.

---

## Phase 1 — Public Scanner · weeks 1–2

**Ships:** the free, no-signup scanner at the root of the site. Enter a hostname, get a graded report with a shareable link.

| In scope | Out of scope |
|---|---|
| Monorepo, Docker Compose, CI-ready lint/test setup | Any authentication |
| All 7 scan modules (cert, chain, TLS, DNS, email auth, headers, readiness) | Accounts, billing, saved hostnames |
| Grading engine + finding catalogue | Scheduled re-scanning |
| Async scan queue with polling | Alerts of any kind |
| Result page + shareable public slug URL | PDF export |
| Landing page, countdown page, findings docs pages | The sidecar |
| SSRF guard + rate limiting | Multi-tenancy |

**Why first:** it is the marketing engine and the lead qualifier. It acquires customers while you sleep, ranks in search permanently, and every failed grade is a sales conversation. Nothing else can be sold until this exists.

**Done when:** a stranger can scan a domain on their phone in under 20 seconds and share the result in a WhatsApp group.

---

## Phase 2 — Accounts, Monitoring & Billing · weeks 3–5

**Ships:** the ₹999 Watch tier. This is the first phase that takes money.

- Email + OTP auth, organisations, roles (`owner`, `admin`, `member`)
- Monitored hostname lists with per-plan quotas (3 free / 25 Watch / 100 Watch Pro)
- Scheduled re-scan every 6 hours via the worker
- Alert engine: 60 / 30 / 14 / 7 / 3 / 1 days before expiry, plus grade regression, plus scan failure
- Channels: email, Slack webhook, generic webhook, WhatsApp via a BSP
- Alert de-duplication and quiet hours (the thing that makes alerting tolerable)
- Razorpay (INR) + Stripe (USD), plan gating, invoices, GST fields
- Dashboard: hostname table, per-hostname history, upcoming-expiry view

**Contract additions needed:** `Organisation`, `User`, `MonitoredHostname`, `AlertRule`, `AlertEvent`, `Subscription`, `Plan`. Auth scheme (JWT in httpOnly cookie). Paginated list envelope.

**Cash impact:** first recurring revenue. Payment method on file is what makes every later upsell a warm conversation.

---

## Phase 3 — Readiness Calculator & Reports · weeks 5–6

**Ships:** the lead magnet and the ₹15,000 one-off audit.

- Public calculator: hostname count + current process → renewals/year for 2026, 2027, 2029, engineer-hours, cost at Indian salary benchmarks
- Bulk import: paste or upload up to 500 hostnames, batch scan, portfolio-level readiness grade
- Branded PDF: portfolio report, per-hostname readiness grade, remediation list
- Report delivery by email, gated on address capture
- Admin view to run a portfolio scan on a prospect before contacting them

**Contract additions:** `PortfolioScan`, `ReadinessEstimate`, `ReportJob`. PDF generation pinned to one library.

**Cash impact:** fastest line item. No subscription friction, invoiced and paid inside a week, converts to subscription at high rates because you have just shown them the problem in their own numbers.

---

## Phase 4 — Sidecar: Auto-TLS · weeks 7–8

**Ships:** the Secure tier, ₹7,999. The first thing that requires installing something.

- Rust sidecar, Apache 2.0, on GitHub
- ACME client: Let's Encrypt primary, ZeroSSL fallback, HTTP-01 and DNS-01, wildcards
- Renewal at ⅓ of lifetime remaining, hot reload without restart
- **Renewal-failure alerting** — silent certbot failure is the actual killer, not the absence of certbot
- Enrolment flow: one command, one token, sidecar appears in the dashboard
- Fleet view: every sidecar, every certificate, every renewal attempt

**Contract additions:** `Agent`, `AgentEnrolment`, `Certificate`, `RenewalAttempt`. Agent↔control-plane protocol (mTLS, heartbeat interval, payload shapes) needs its own contract section.

**Positioning note for the build:** never position against certbot or Caddy — you lose that fight and annoy developers. Position against the *absence of fleet visibility, failure alerting, and audit evidence*.

---

## Phase 5 — Agency / MSP Console · weeks 9–10

**Ships:** the ₹39,999+ tier. The largest single lever on near-term cash.

- Client grouping under one agency account
- Bulk domain import per client
- White-labelled PDF reports (agency logo, agency colours, your engine)
- Consolidated alert digest across all clients
- Per-client and consolidated invoicing, partner margin
- Reseller price sheet so the agency marks the product up

**Contract additions:** tenancy model (`Agency` → `Client` → `MonitoredHostname`), branding assets, digest scheduling.

**Why it matters:** one agency contract is worth 15–25 direct SMB logos, churns below 1%, and expands every time they win a client. Ten contracts is ₹6L+ MRR.

---

## Phase 6 — Shadow Mode & Compliance Pack · weeks 11–12

**Ships:** the ₹18,999 Compliance tier, and the feature that removes the last objection to the sidecar.

- Shadow enforcement: every policy runs observe-only by default. The sidecar evaluates, logs "would have blocked", forwards the request anyway.
- Shadow dashboard: "In the last 14 days, 1,247 requests would have been blocked. 340 were credential-stuffing attempts against /login."
- One-click promotion from shadow to enforce, per policy, with instant rollback
- Policy version history
- Evidence pack: TLS inventory, policy definitions and change history, enforcement decision logs, control mapping to DPDP rules, SOC 2 CC6.x, ISO 27001 Annex A
- One-year log retention, auditor-ready PDF + raw JSON export

**Contract additions:** `Policy`, `PolicyVersion`, `ShadowDecision`, `EvidencePack`, `ControlMapping`.

**Two hard rules for this phase:**
1. Fail-open is the default state, not a fallback. Nothing the sidecar does can break a customer's traffic.
2. The product sells **evidence for controls we actually enforce** — never "DPDP compliance". A lawyer reviews every compliance claim before it ships. Honesty is the differentiator against incumbents; trading it for a quarter of faster sales is the worst deal available.

---

## Sequencing dependencies

```
Phase 1 ──┬── Phase 2 ──┬── Phase 3
          │             ├── Phase 5
          └── Phase 4 ──┴── Phase 6
```

Phase 3 needs Phase 2's account model. Phase 5 needs Phase 2's tenancy. Phase 6 needs Phase 4's sidecar. Phases 3 and 4 can be built in either order — take Phase 3 first if cash is tight, Phase 4 first if you have a customer waiting on automation.

---

## How to run each phase

1. Open a **new chat** for the phase.
2. Paste `CONTRACT.md` in full as the first message.
3. Paste the phase prompt as the second message.
4. Build in the order the phase prompt specifies. Do not let the session jump ahead.
5. When the phase's definition of done is met, come back for the next phase prompt and the contract amendment that goes with it.

If a coding session says "I've simplified this" or "for brevity", stop it and make it produce the complete file. Silent simplification across sessions is how the frontend and backend drift apart.
