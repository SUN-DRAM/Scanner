# Feature Prompt — PDF Report Export

> Paste into a fresh Claude Code session in `D:\Scanner`. `CLAUDE.md` and `CONTRACT.md` (v2.8) are auto-loaded and binding.

---

Add a **Download PDF Report** capability to the existing scan result. This is an export layer over the scan result we already produce — not a new scanner, not a new grading engine, not a second source of truth.

Read the existing implementation before proposing anything: `app/scanner/orchestrator.py`, `app/grading.py`, `app/findings.py`, the `Scan` shape in contract §6.1, the `scans.result` JSONB column, and the `ScanResultView` / `ScanResultBody` components.

## Why we're building it

We're running outreach: scanning prospect agencies' client portfolios and leading with findings rather than a pitch. Preparing each report by hand doesn't scale past a handful of domains. The PDF is the artefact we attach to that email — so it has to look like something a stranger would open, read, and forward internally.

It should also be good enough to ship to customers later. Build it as a product feature, not an internal script.

---

# PDF Export — Step 1 decisions (paste into the session)

All three decisions are settled. Proceed to the contract amendment, then build.

---

## 1.1 Branding — keep §12

The PDF uses the contract §12 tokens unchanged: ink `#0B1B2B`, paper `#F6F8FA`, cobalt `#1B4DFF`, line `#E3E8ED`, and the existing `--pass` / `--warn` / `--alert` severity colours. No gold, no separate palette.

Rationale: a prospect receives the PDF and then clicks through to `sundram.tech`. Those two must look like the same company. Brand work can happen later as a deliberate site-wide decision, not as a side effect of an export feature.

**Fonts matter here and are easy to get wrong.** §12 specifies Space Grotesk (display), Inter (body) and JetBrains Mono (wire values). Whatever renderer you pick will silently fall back to a default face if those aren't available inside the container, and the PDF will look nothing like the site. Bundle the TTF/WOFF files in the repo, register them explicitly, and assert in a test that the output embeds the expected font names rather than a fallback.

---

## 1.2 Generation — backend, WeasyPrint, from the stored JSONB

**Where:** the API, reading `scans.result` (the full `Scan` object from §6.1). No re-scan, no HTML scraping, no second source of truth.

**Library: WeasyPrint.** Reasons, in order:

1. It renders HTML + CSS, so the §12 tokens are reused literally as CSS custom properties rather than re-expressed imperatively in Python. Given decision 1.1, that's the difference between "consistent by construction" and "consistent until someone edits one of them."
2. `@page` margin boxes give repeating footers and `counter(page)` / `counter(pages)` for "page N of M" for free — a hard requirement that's fiddly in ReportLab.
3. `break-inside: avoid` on a finding block solves the "a title must not be orphaned at the bottom of a page" requirement declaratively.
4. Headless-browser rendering (Playwright/Puppeteer) is rejected outright: production is a 4GB box running seven containers, and a Chromium process is the heaviest thing that would ever run on it.

**If WeasyPrint turns out to be a poor fit once you've looked at it properly, say so and recommend ReportLab Platypus instead.** I want the reasoning checked, not obeyed.

**Docker consequences:** WeasyPrint needs Pango, Cairo and GDK-PixBuf. Install them via `apt` in the API image and report the image size delta. If the API image is Alpine-based, note that — WeasyPrint on Alpine is known to be painful and moving to `python:3.12-slim` may be the cleaner path. Flag it rather than fighting it.

**Concurrency — important.** PDF rendering is synchronous and CPU-bound. Called directly in an async handler it blocks the event loop, which would violate §7.3's requirement that scan-state endpoints respond in under 300ms while work is in flight. Run it in a thread pool (`starlette.concurrency.run_in_threadpool`) behind a semaphore capped at **2 concurrent renders**, so the export path can never starve the scanner. The scanner is the acquisition channel and takes priority, same rule as the scheduler.

**Caching: yes.** A completed scan is immutable, so its PDF is too. Cache the bytes in Redis keyed on `scan_id`, TTL 24h, with a size guard that skips caching anything unusually large. This isn't premature — a shared scan link posted in a Slack or WhatsApp group means many people hitting download on the same `scan_id`, which is exactly the cheap-to-prevent load spike.

---

## 1.3 Contract amendment v2.9

### Endpoints (§7)

```
GET /api/v1/scans/{scan_id}/report.pdf
GET /api/v1/scans/slug/{public_slug}/report.pdf
```

Mirrors the existing pair of scan GET endpoints — same lookup semantics, same 404 behaviour.

- `200` → `application/pdf`, `Content-Disposition: attachment; filename="..."`
- `404 SCAN_NOT_FOUND` → unknown id or slug
- `409 REPORT_NOT_AVAILABLE` → **new error code**, returned when `status` is anything other than `completed`

### Failed and in-progress scans get no PDF

A `failed` scan has no grade, no findings and no modules — a PDF of it would be an empty document with our logo on it, which is worse than no document. Return `409 REPORT_NOT_AVAILABLE`.

The frontend must not render a download button that leads to a 409. Hide it entirely unless `status === "completed"`.

### Filename

```
SUN-DRAM-Security-Report-{hostname}-{YYYY-MM-DD}.pdf
```

Date is the scan's `completed_at` in IST. Note that §7.2 already normalises IDN hostnames to punycode before storage, so the stored hostname is ASCII `[a-z0-9.-]` and needs no further sanitisation — but assert that in a test rather than assuming it, and strip anything unexpected defensively.

### New env vars (§4)

```
RATE_LIMIT_PDF_PER_IP_PER_HOUR=10
PDF_CACHE_TTL_SECONDS=86400
PDF_MAX_CONCURRENT=2
```

10 per IP per hour is generous for real use and closes the abuse path on an unauthenticated, CPU-expensive public endpoint. Reuse the existing §10 Redis sliding-window limiter — do not write a second one.

### No §11 change

Caching lives in Redis. No new table.

### Amendment log

Bump §14 to **v2.9**. Record the `REPORT_NOT_AVAILABLE` addition to §7.4's closed error set, the two endpoints, the three env vars, and the decision that non-completed scans have no PDF.

---

## Proceed

Write the amendment, show me the diff, then build. Same working agreement as always: complete files, one step at a time, stop and wait.

One addition to the test list: after implementing, run the full existing suite and confirm the count is unchanged plus your new tests. This feature touches shared code paths, and the thing I care about most is that the scanner still works exactly as it did.

## Step 2 — The report

Once the decisions are settled, build it.

### Structure

**Cover:** logo, "SUN-DRAM", "External Security Assessment", target hostname in mono, scan timestamp in IST with UTC offset, the overall grade and score, and the `headline` string the backend already produces. One line stating what this is: an external, unauthenticated assessment of a single hostname.

**Executive summary:** overall grade and score, the `counts` object broken out by severity, and the modules table with each module's grade and its backend-authored `summary` string. Nothing invented — if the scan result doesn't have a number, it doesn't go in.

**Certificate validity:** the validity window with `not_before`, `not_after`, days remaining, and the 15 March 2027 threshold marked. This is the Validity Bar from §12 and it's the single most persuasive element in the whole document — it's the thing that makes the deadline feel real to someone who hasn't thought about it. Give it proper space.

**Readiness:** the readiness module's verdict, verdict reason, renewals per year for now / 2027 / 2029, and the countdown. For our outreach this is the section that creates the conversation, so it gets its own page area, not a footnote.

**Findings, grouped by severity, critical first.** Per finding: title, severity, module, description, evidence, remediation, and the `docs_path` rendered as a `sundram.tech` URL so the reader can go deeper.

**Footer on every page:** SUN-DRAM · Infrastructure security monitoring · sundram.tech · page N of M.

### Non-negotiable content rules

- **Every string comes from the stored scan result.** Do not rewrite, summarise, re-tone or "improve" any title, description or remediation. The web report and the PDF must say the same thing in the same words — if they diverge, one of them is wrong and we won't know which.
- **Never recompute a grade, score, severity or count.** Read them.
- **No claim language.** Never "certified", "compliant", "audited", "penetration test", or "security certification". This is an external assessment. Compliance-washing is a legal tripwire and our honesty is the thing that differentiates us from incumbents — spending it on a nicer-sounding PDF would be the worst trade available.
- **No internal detail.** No infrastructure specifics, no request ids, no stack information, nothing not already visible on the public result page.

### Layout requirements

- Must survive 1 page and 15 pages equally
- Long descriptions and remediation text flow across page breaks without overlap, cut-off or orphaned headings
- A finding never splits so that its title lands alone at the bottom of a page
- No large blank pages
- Clean scans with zero findings still produce a complete, confident-looking report — an A+ result should feel like a good outcome, not an empty template
- Hostnames, dates, serial numbers and anything else off the wire set in mono, per §12

---

## Step 3 — Tests

- Clean A+ scan, no findings
- A typical scan with a handful of findings across severities
- A scan with critical findings
- A synthetic scan with 40+ findings spanning many pages
- A finding with a very long remediation string
- A failed scan — decide and document whether a PDF is offered at all for `status: "failed"`, and make the UI consistent with that decision
- Filename sanitisation, including an IDN hostname and a hostname with unusual characters
- **PDF content matches the web report exactly** for the same `scan_id` — assert on grade, score, counts, and every finding code present
- No re-scan is triggered: assert the scan count in the database is unchanged after a PDF request
- The rate limit trips and returns `429 RATE_LIMITED`
- Peak memory during generation of the largest report, measured on the container — I need to know this fits on a 4GB box alongside everything else

Then generate one for `google.com` and one for `sundram.tech`, and show me both. I'll judge whether it's good enough to attach to a cold email, because that's the only acceptance test that actually matters.

---

## Out of scope

No white-labelling, no report templates, no customisation, no scheduled reports, no batch export in this pass, no changes to scanning, grading, findings or billing. Add the button where the existing result actions live and nothing more.

Start with Step 1. Answer the three decisions and wait.