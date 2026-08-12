# Phase 1 Gate — verify, close the funnel, ship

Three prompts, run in order, in Claude Code. Do not start Phase 2 until all three are done.



---

# Gate A — Accuracy verification

> Paste into Claude Code as a fresh session.

Phase 1 is feature-complete but has never been run against real domains in the environment it deploys to. Before we build anything else, prove the scanner is correct. Accuracy is the product — a false "expiring in 3 days" on a healthy certificate is worse than having no product at all.

## A1. Close the Docker-only gap

Bring up the full stack with `docker compose up --build` and run the complete suite inside the containers, including the 16 tests currently skipped as Docker-only. Report the real pass count. If any of those 16 fail, that is a Phase 1 bug, not a Phase 2 problem — fix it now.

Specifically confirm inside Docker:
- the DB-backed scan endpoints (`POST /api/v1/scans`, both GETs) round-trip correctly
- Alembic migrations apply cleanly to an empty database
- the docs volume mount resolves all 42 finding docs
- the OG image route renders on Linux, confirming your `@vercel/og` Windows diagnosis

## A2. Build a real-domain accuracy harness

Create `apps/api/tests/accuracy/` with a runnable script (not part of the normal `pytest` run — it needs live network) that scans a fixed corpus and asserts expected outcomes.

**Known-bad corpus** — every one must produce the correct finding, not a crash:
`expired.badssl.com`, `self-signed.badssl.com`, `wrong.host.badssl.com`, `untrusted-root.badssl.com`, `incomplete-chain.badssl.com`, `sha1-intermediate.badssl.com`, `rc4.badssl.com`, `dh480.badssl.com`, `tls-v1-0.badssl.com`, `no-subject.badssl.com`, `1000-sans.badssl.com`, `no-common-name.badssl.com`

**Known-good corpus** — every one must produce **zero** findings of severity `high` or `critical`:
`google.com`, `cloudflare.com`, `github.com`, `letsencrypt.org`, `razorpay.com`, `zerodha.com`

**Indian real-world corpus** — no assertions, but print full results for me to eyeball. These are the messy production setups our buyers actually run:
`irctc.co.in`, `sbi.co.in`, `incometax.gov.in`, `uidai.gov.in`, `flipkart.com`, `swiggy.com`, and three `.ac.in` university domains

**Edge cases** — must degrade gracefully, never crash, never invent data:
- a domain that does not exist
- a domain that resolves but refuses port 443
- a domain with no MX records
- a domain with no CAA record
- an IDN domain
- a hostname behind Cloudflare (proxied cert, not origin cert)
- a wildcard certificate
- a hostname where WHOIS fails or is redacted

## A3. Cross-check against ground truth — this is the important one

For ten domains spanning the corpus, independently verify our output against a second source and report a diff table:

- `openssl s_client -connect <host>:443 -servername <host>` for `not_before`, `not_after`, issuer, chain order
- `crt.sh` for certificate transparency
- `dig` for every DNS assertion we make

**Any disagreement is a bug in our scanner, not in the reference.** List every discrepancy explicitly. Do not explain one away — if `days_until_expiry` is off by one because of a timezone or rounding decision, that is exactly the class of bug that destroys trust, and I want to see it.

## A4. False-positive sweep

Scan the six known-good domains twice, ten minutes apart. Assert:
- zero `CERT_EXPIR*` findings on any of them
- identical grades across both runs (no non-determinism)
- `days_until_expiry` differs by at most 1 between runs

## A5. Load and safety sanity

- 50 concurrent scans against mixed targets — no crashes, no connection-pool exhaustion, no scans stuck in `running` forever
- confirm the rate limiter trips at the configured threshold and returns a correct `retry_after_seconds`
- confirm a scan that exceeds `SCAN_TIMEOUT_SECONDS` lands in `failed` with a shareable page, never hangs
- re-confirm the SSRF guard against a live DNS name that resolves to `127.0.0.1` (register one or use `localtest.me`)

**Deliverable:** a written accuracy report at `docs/ACCURACY_REPORT.md` with the diff table, every discrepancy found, and what you fixed. Stop and show me the report before touching Gate B.

---

# Gate B — Close the funnel loop

> Only after Gate A passes.

Right now every visitor is unrecoverable. Someone scans their domain, sees a C grade, closes the tab, and we have nothing. Phase 2 (accounts and alerting) is weeks away, and every visitor between now and then is wasted. This is a half-day of work that makes the entire Phase 1 traffic window monetisable.

Add the minimum viable capture, and nothing more:

1. **Email capture on the result page.** Below the grade, one field: *"Get alerted before this certificate expires."* Not a modal, not an interstitial, not a paywall — an inline field the user can ignore. Submitting stores `email`, `hostname`, `scan_id`, `created_at`, and a hashed IP in a new `waitlist_signups` table. Response copy: *"We'll email you 30 days before {hostname} expires."* Then honour that promise in Phase 2.

2. **Anonymous usage counters.** A `daily_stats` view or table recording scans started, scans completed, scans failed, share-link opens, and waitlist signups, per day. No personal data. We need scan→capture conversion as a real number, because contract §13's success metrics are meaningless without it.

3. **A minimal `/admin/stats` page** behind a single env-var token (`ADMIN_TOKEN`) showing those counters and the last 100 scanned hostnames. This is not a dashboard — it is a text table. It exists so I can run the scanner across agency prospect portfolios in week 3 and see the results.

Add `waitlist_signups` and `daily_stats` to `CONTRACT.md` §11 and bump the amendment log to v1.1. Do not add auth, plans, billing, or scheduled scanning — those are Phase 2 and building them now is scope creep.

---

# Gate C — Ship it

> Only after Gates A and B pass.

Target: a single VPS running the existing Docker Compose stack, in an Indian region so first-byte time is low for the audience and for search.

**Recommended:** DigitalOcean Bangalore or AWS Mumbai, 4GB/2vCPU, roughly ₹1,500–2,500/month. Do not use a serverless platform — the scanner holds long TLS handshakes and background workers, which is the wrong shape for it.

Produce:

1. `docker-compose.prod.yml` — production overrides, no bind mounts of source, restart policies, resource limits on the worker
2. **Caddy as the reverse proxy** with automatic HTTPS. We are a certificate company; our own certificate will be automated, and Caddy is what we will honestly recommend to customers who do not need fleet visibility.
3. `deploy.md` — a numbered runbook: provision, DNS, first deploy, redeploy, rollback, restore-from-backup. Written so I can follow it at 2am.
4. **Postgres backups** — nightly `pg_dump` to object storage, and a documented restore that you have actually tested by restoring into a scratch container.
5. **Error tracking** — Sentry or equivalent on both api and web. Free tier is fine. Without this, a production bug is invisible until a customer complains, and by then the trust is gone.
6. **Uptime monitoring** on `/api/v1/health` from an external service, alerting to my phone.
7. `.env.production.example` with every variable and a one-line note on each.
8. **Log hygiene:** confirm no raw IPs, no email addresses, and no full request bodies reach the logs. DPDP posture starts on day one, not at audit time.

## The credibility check

After deploy, scan our own domain with our own scanner.

**If it does not grade A+, fix our site before announcing anything.** A certificate-readiness product whose own site scores B is the single most avoidable credibility failure available to us. That means HSTS with a long max-age, a complete chain, TLS 1.3, CSP, and a CAA record on our own domain.

Then verify on a real phone on mobile data — not a desktop browser at 360px — that a shared scan link loads and reads correctly. That is the actual distribution mechanism: someone pastes the link into a WhatsApp group.


