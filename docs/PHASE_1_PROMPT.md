

---

You are the lead engineer building Phase 1 of the SUN-DRAM Scanner. Read CONTRACT.md and ROADMAP.md in full before you write anything. They are binding. You are building Phase 1.. Read it properly before you write a line of code.

## Your working agreement

- **The contract wins every time.** If something you want to write contradicts it, stop and reply with `CONTRACT GAP: <what's missing or wrong>` and wait for me. Do not invent a field name, an enum value, an error code, or an endpoint.
- **Complete files only.** Every file you output is the whole file, ready to save. No `# ... unchanged`, no `// rest of implementation`, no placeholder function bodies, no "you can add X later".
- **One step at a time.** Build in the order below. At the end of each step, stop, list the files you produced with their full paths, and wait for me to say "next". Do not run ahead.
- **State your assumptions out loud.** If you have to choose something the contract doesn't specify, say what you chose and why, in one line, before the code.
- **Accuracy over cleverness.** This scanner's first job is to never be wrong about a certificate. A false "expiring in 3 days" on a healthy certificate is worse than no product. Where a check is uncertain, return `null` and say so rather than guessing.

I am running Windows with the repo at `D:\Scanner`, using Docker Desktop. Give me Windows-safe commands (PowerShell), and make sure line endings, paths, and volume mounts work there.

## What Phase 1 is

A free, public, no-signup TLS and DNS scanner. A stranger types a hostname, gets a graded report in under 20 seconds, and can share the result as a link. No accounts, no billing, no scheduling, no alerts, no sidecar — those are later phases, and building any of them now is scope creep I will reject.

Target user: a non-specialist founder or agency owner in India with 15–60 hostnames who has never thought about certificate lifetimes and is about to have a problem in March 2027. Everything the product says must make sense to them.

## Build order

### Step 1 — Skeleton and infrastructure
- Full repo tree exactly as contract §3.2, with every directory created
- `docker-compose.yml`: postgres 16, redis 7, api, worker, web. Named volumes. Health checks on postgres and redis. api and worker depend on both being healthy.
- `.env.example` with exactly the variables in contract §4
- `apps/api/pyproject.toml` and `Dockerfile` (multi-stage, non-root user)
- `apps/web/package.json`, `Dockerfile`, `next.config.ts`, `tailwind.config.ts` with the tokens from contract §12
- `apps/api/app/config.py` using pydantic-settings
- `apps/api/app/main.py` with the app factory, CORS from `CORS_ORIGINS`, the `X-Request-ID` middleware, and exception handlers wired
- `apps/api/app/routers/health.py` returning `{"status":"ok","database":"ok","redis":"ok","version":"1.0.0","checked_at":"..."}`
- `README.md`: setup in under ten lines
- `.gitignore`, `ruff.toml`, `mypy.ini`, eslint and prettier config

**Gate:** `docker compose up` must work end to end and `/api/v1/health` must return 200 before we move on. I will run it and tell you.

### Step 2 — Contract types, enums, errors, database
- `apps/api/app/enums.py` — every enum in contract §5, no additions
- `apps/api/app/schemas.py` — Pydantic v2 models for every shape in contract §6. Field names identical to the contract. Use `model_config = ConfigDict(from_attributes=True)` where relevant. No aliases, no camelCase.
- `apps/api/app/errors.py` — the envelope and every code from contract §7.4, plus FastAPI exception handlers so *nothing* can return a non-conforming error
- `apps/api/app/models.py` + first Alembic migration — schema exactly as contract §11
- `apps/api/app/db.py` — async engine and session dependency
- `apps/web/types/contract.ts` — hand-written TypeScript mirror. Every type, every enum as a union of string literals. This file and `schemas.py` must match field for field; show me the two side by side in your summary.

### Step 3 — Safety layer
This comes before any scanning code, deliberately.
- `apps/api/app/safety.py` — hostname normalisation exactly as contract §7.2, resolve-then-validate, the full private/reserved range blocklist from §10, the static host denylist, IP-pinned connection helper, redirect revalidation, response size cap
- `apps/api/app/ratelimit.py` — Redis sliding window, per-IP and per-hostname, returning `retry_after_seconds`
- Tests: a private IP is rejected, `169.254.169.254` is rejected, port 22 is rejected, an IDN hostname normalises to punycode, `https://Example.COM/path?q=1` normalises to `example.com`, the rate limiter trips at the configured threshold

### Step 4 — Finding catalogue and grading engine
- `apps/api/app/findings.py` — every code from contract §8 as a registry: code, module, default severity, and the templates for `title`, `description`, `remediation`, `docs_path`. Written in plain English for a founder, not a security engineer.
- `apps/api/app/grading.py` — contract §9 implemented exactly: module scores, weighted overall, re-normalisation when a module errors, the grade bands, the critical and double-high caps, the headline selection
- Tests with fixed fixtures asserting exact numbers: a clean site scores A+, an expired certificate forces F, two high findings cap at C, a dropped module re-normalises correctly

Grading must be a pure function. No I/O, no clock reads inside it — pass `now` in.

### Step 5 — The seven scan modules
One file per module in `apps/api/app/scanner/`, each with the same signature, each returning a `ModuleResult`, each with its own 8-second timeout, each catching every exception into `status: "error"` rather than raising.

- `certificate.py` — TLS handshake via `cryptography` + `ssl`, all fields in contract §6.4
- `chain.py` — chain completeness, order, trusted root, intermediate expiry
- `tls.py` — protocol support probed per version, negotiated cipher, weak cipher and forward-secrecy detection
- `dns_records.py` — `dnspython` for A/AAAA/CNAME/NS/MX/CAA/DNSSEC, WHOIS for registrar and domain expiry. WHOIS is unreliable: on failure return `null` fields, never a wrong date, and never a `DOMAIN_EXPIRING_*` finding from a failed lookup.
- `email_auth.py` — SPF parse with lookup counting, DMARC parse, DKIM best-effort selector probing
- `headers.py` — one GET to `http://` to check the redirect, one to `https://`, parse every header in contract §6.4
- `readiness.py` — the phase constants, the countdown, and the verdict rules from contract §6.4. This is the module that makes the product distinctive; give it care.
- `orchestrator.py` — runs all seven concurrently with `asyncio.gather(return_exceptions=True)`, respects the whole-scan budget, assembles the `Scan` object, calls grading, persists

### Step 6 — API endpoints and worker
- `routers/scans.py` — `POST /api/v1/scans` (202, with the cache-hit 200 path), `GET /api/v1/scans/{scan_id}`, `GET /api/v1/scans/slug/{public_slug}`
- `routers/meta.py` — `GET /api/v1/meta/deadlines`
- `worker.py` — arq worker, enqueues from the POST handler, marks `running` then `completed` or `failed`
- Slug generation with `secrets`, collision retry
- The GET endpoints must return in under 300ms while a scan runs — read state, never block
- Tests: full request/response shape assertions against the contract for every endpoint, including a hostname that does not resolve returning a `failed` Scan rather than an HTTP error

### Step 7 — Frontend
- `lib/api.ts` — the only place `fetch` is called. Typed against `types/contract.ts`. Handles the polling loop from contract §7.3: 1500ms interval, 90s ceiling, stops on terminal status.
- `app/page.tsx` — landing page. The hero is the scan box, not a marketing block. Above it, one sentence naming the deadline. Below it, the countdown to 15 March 2027 pulled from `/api/v1/meta/deadlines`.
- `app/scan/[slug]/page.tsx` — the result page. Server-rendered for shareability with correct OG tags showing hostname and grade. Sections in this order: grade + headline, the Validity Bar, findings by severity, the seven module cards.
- Components: `ScanForm`, `GradeDial`, `ValidityBar`, `ModuleCard`, `FindingRow`, `ScanProgress`
- `app/countdown/page.tsx`, `app/docs/findings/[code]/page.tsx`
- Loading state: show progress per module as it lands, not a spinner. The scan takes seconds and the user should see it working.
- Empty and error states written per contract §12 voice: state what happened and what to do, never apologise, never "Oops".

Follow contract §12 exactly for colour, type, spacing and the accessibility floor. The **Validity Bar** is the signature component and the one place to spend extra design effort: `not_before` on the left, `not_after` on the right, today's marker, and the 15 March 2027 threshold marked on the timeline, with the certificate's own dates as mono labels. Everything else stays quiet and disciplined.

Do not use `localStorage` or `sessionStorage`. Do not add a state management library — React state and server components are enough.

### Step 8 — Content, docs, polish
- `docs/findings/*.md` for all 42 finding codes: title, what it means, why it matters, how to fix. Founder-readable.
- Five SEO landing pages targeting: `ssl certificate expiry monitoring`, `100 day certificate 2027`, `certbot alternative docker`, `nginx auto ssl renewal`, `free ssl checker india`
- `sitemap.xml`, `robots.txt`, OG image generation for scan results
- Final pass: `pytest`, `ruff check`, `mypy`, `pnpm lint`, `pnpm build` all green
- Responsive check at 360px, 768px, 1440px

## Acceptance for Phase 1

Everything in contract §13, plus:

- Scanning `google.com`, `expired.badssl.com`, `self-signed.badssl.com`, `wrong.host.badssl.com`, `untrusted-root.badssl.com`, and a domain that does not exist all produce sensible, correct, non-crashing results
- A scan of a healthy site with a 90-day Let's Encrypt certificate returns readiness verdict `automated` and `survives_2027: true`
- A scan of a site with a 398-day certificate returns verdict `manual` and a `READINESS_MANUAL_2027` finding
- The shareable link opens for a logged-out stranger on mobile and renders the full report
- Total time from pressing Scan to seeing a grade is under 20 seconds on a normal connection

## Start now

Begin with Step 1 only. Before any code, give me a four-to-six line plan for Step 1 and flag anything in the contract you think is wrong, ambiguous, or will cause you trouble later — I would much rather fix the contract now than discover the problem in Step 6.
