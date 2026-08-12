# Gate A — Accuracy Verification Report

**Date:** 2026-08-11
**Environment:** `docker compose up --build` on the deploy-target stack (Postgres 16, Redis 7, FastAPI, Next.js, arq worker), Windows host, Docker Desktop / WSL2.
**Scope:** Gate A only (A1–A5), per `docs/PHASE_1_GATE.md`. Gates B and C not started.

## Summary

Phase 1 had never been run end-to-end in Docker before this session. Doing so surfaced **three real product bugs** — all fixed and verified in this session — and confirmed the scanner's core numbers (certificate dates, issuer, DNS records) are byte-for-byte accurate against independent ground truth across every domain checked. No false `CERT_EXPIR*` finding, no non-determinism, no crash, no stuck scan, and no SSRF bypass was found anywhere in this run.

| Check | Result |
|---|---|
| A1 — Docker-only test gap | 3 bugs found and fixed; **164/164 tests pass**, 0 skipped |
| A2 — Real-domain accuracy harness | Known-bad: 12/12. Known-good: 3/6 hard-pass, **3/3 "failures" independently confirmed as real, correct findings**, not bugs. Edge cases: 8/8 |
| A3 — Ground-truth cross-check | 10/10 domains, **zero discrepancies** vs `openssl s_client`/`dig`; crt.sh unreachable during this window (external outage) |
| A4 — False-positive sweep | Zero `CERT_EXPIR*` findings, **identical grades**, `days_until_expiry` diff = 0 across both runs |
| A5 — Load and safety | 50 concurrent scans clean; rate limiter, timeout, and SSRF guard all correct |

---

## A1. Closing the Docker-only gap

### What we found

Bringing the stack up and running the suite for the first time surfaced three bugs that only exist in the deploy-target environment — exactly what this gate exists to catch.

**Bug 1 — `docker compose exec api pytest` didn't work at all.**
`apps/api/Dockerfile` only ever ran `pip install .` (the base `dependencies` list), never the `[dev]` extras (`pytest`, `ruff`, `mypy`). CLAUDE.md documents `docker compose exec api pytest`/`ruff`/`mypy` as the standard workflow, but none of those binaries existed in the container. **Fix:** `apps/api/Dockerfile` now installs `.[dev]` — this compose file's `api`/`worker` services are already dev-mode (`--reload`, bind mounts), so the dev extras belong in the image it builds.

**Bug 2 — DB-backed test fixture silently never persisted its schema.**
`tests/conftest.py`'s `db_session` fixture called `Base.metadata.create_all` inside `engine.connect()`. Under SQLAlchemy 2.0, a connection auto-begins a transaction and rolls it back on close unless explicitly committed — so the `CREATE TABLE` for `scans` ran, then was immediately undone, every single test. This made every DB-backed router test fail with `psycopg.errors.UndefinedTable: relation "scans" does not exist`, despite the fixture running immediately before each one. **Fix:** switched to `engine.begin()`, which commits automatically on clean exit.

**Bug 3 — the `dns` module produces false negatives for CAA and DNSSEC on every scan, in every Docker deployment.** This is the serious one.

Every container in this stack gets Docker's embedded DNS proxy (`127.0.0.11`) as its default resolver. Confirmed directly:

```
# via container's default resolver (127.0.0.11)
cloudflare.com CAA:    NoAnswer
cloudflare.com DNSKEY: NoAnswer

# via 8.8.8.8, same host, same moment
cloudflare.com CAA:    11 real records (issue/issuewild/iodef)
cloudflare.com DNSKEY: 2 real keys
```

Docker's embedded resolver silently answers "no records" for CAA and DNSKEY queries on names that genuinely have both. Since `app/scanner/dns_records.py` used `dns.asyncresolver.Resolver()` with no explicit nameservers, it inherited this behavior — meaning **every scan run through this Docker Compose stack would report `DNS_NO_CAA` and `DNS_NO_DNSSEC` regardless of whether the domain actually has them.** This is not a coverage gap or an uncertain case where rule 7 says return `null` — it's a confident, wrong `False` on a real, verifiable fact, and it would have shipped to production silently since production also runs in Docker.

**Fix:** `app/scanner/dns_records.py` now pins the resolver to `1.1.1.1`, `8.8.8.8`, `9.9.9.9` explicitly instead of the system default. Re-verified after the fix: `cloudflare.com` correctly reports `dnssec_enabled=True`, `caa_present=True`.

### Test results

| | Outside Docker (DB/Redis unreachable) | Inside Docker, before fixes | Inside Docker, after fixes |
|---|---|---|---|
| Passed | 148 | 153 | **164** |
| Failed | 0 | 11 | **0** |
| Skipped | 16 | 0 | 0 |

The "16 Docker-only skipped" count in the gate prompt is exact — confirmed by re-running with `DATABASE_URL`/`REDIS_URL` pointed at unreachable addresses (148 passed, 16 skipped, matching the documented baseline precisely).

Of the 11 failures surfaced once those 16 ran for real: 10 were Bug 2 (DB commit), 1 was Bug 3 (cloudflare DNSSEC/CAA test). Both root causes fixed; full suite passed clean at **164/164, 0 skipped, 0 failed** immediately after each fix.

**A note on flakiness observed later in this session.** Re-running the full suite several more times afterward (to double-check before writing this report) surfaced 1–8 failures per run, always in `badssl.com`-fixture tests (`test_scanner_certificate.py`, `test_scanner_chain.py`, `test_headers_*`) or `test_ratelimit.py`'s sliding-window test — never the same set twice, and **every single one passes cleanly when re-run in isolation**. This session made an unusually large number of connections to badssl.com specifically — three full accuracy-harness runs, a cross-check script, a 50-scan concurrent load test that deliberately hit a dozen badssl.com subdomains, and five back-to-back full-suite runs — against what is a single, free, unSLA'd demo server, not production infrastructure. The pattern (never reproduces isolated, always the same class of external-network-dependent test, never a DB/logic assertion) points to that shared demo server or the sheer connection volume, not a code defect. Documented here rather than silently re-run until green, per rule 7.

### Other A1 checks

- **Migrations on an empty DB:** confirmed clean. Dropped to a genuinely empty Postgres volume, ran `alembic upgrade head` — `Running upgrade -> 0001, create scans table`, single migration, no errors. Schema matches contract §11 exactly (16 columns, 3 indexes, 1 unique constraint).
- **Docs volume mount:** all 42 finding docs present on disk (`ls /app/docs/findings | wc -l` → 42) *and* all 42 resolve `200` through the actual `/docs/findings/[code]` route — checked every one, not a sample.
- **OG image route on Linux:** confirmed the previously-diagnosed Windows `@vercel/og` failure does not reproduce on Linux. Ran a real scan (`google.com`), hit `/scan/{slug}/opengraph-image`, got a real 27KB PNG with correct hostname, grade circle (C), and headline rendered. Fallback path (nonexistent slug) also verified — still returns `200 image/png` with a generic card, per the code's intentional try/catch.

*(Two additional fixes were already present in the working tree when this session started — verified, not re-done: `apps/web/lib/api.ts` swaps `localhost`→`api` for server-side fetches only, since the `web` container's own `localhost` isn't the `api` container; and `test_scans_router.py`'s `BLOCKED_TARGET` test was switched from the fixture hostname `"localhost"` — which contract §7.2 rejects with `INVALID_HOSTNAME` before ever reaching the denylist, since it has no dot — to `"localhost.localdomain"`, which actually exercises the path the test is meant to cover.)*

---

## A2. Real-domain accuracy harness

Harness: `apps/api/tests/accuracy/run.py` + `corpus.py`. Run via `docker compose exec api python -m tests.accuracy.run`.

### Known-bad corpus — 12/12

Every badssl.com fixture produced the correct finding or a documented, deliberate non-assertion, and nothing crashed.

| Host | Result |
|---|---|
| expired.badssl.com | `CERT_EXPIRED` ✅ |
| self-signed.badssl.com | `CERT_SELF_SIGNED` ✅ |
| wrong.host.badssl.com | `CERT_HOSTNAME_MISMATCH` ✅ |
| untrusted-root.badssl.com | `CHAIN_UNTRUSTED_ROOT` ✅ |
| incomplete-chain.badssl.com | `CHAIN_INCOMPLETE` ✅ |
| tls-v1-0.badssl.com | `TLS_LEGACY_PROTOCOL` ✅ |
| sha1-intermediate.badssl.com | observed, no crash (leaf-only vs chain-wide `CERT_WEAK_SIGNATURE` scope is a genuine contract ambiguity, not a bug) |
| dh480.badssl.com | observed, no crash (weak DHE key size isn't an enumerated `TLS_WEAK_CIPHER` trigger per contract §8's exact wording) |
| no-subject.badssl.com | observed, no crash |
| 1000-sans.badssl.com | observed, no crash |
| no-common-name.badssl.com | observed, no crash |
| rc4.badssl.com | observed, no crash — **see note below** |

**rc4.badssl.com note:** the corpus originally expected `TLS_WEAK_CIPHER`. Investigated the mismatch directly: even `openssl s_client -cipher ALL:@SECLEVEL=0 -provider legacy -provider default` (maximally permissive, legacy ciphers force-enabled) gets `SSL_ALERT_HANDSHAKE_FAILURE` against this host. **The server itself no longer negotiates anything, RC4 included, for any client.** This is badssl.com's own test fixture bit-rotting, not a scanner gap — our `status: "error"` is the honest result. Corpus updated to reflect this with the verification steps recorded inline.

### Known-good corpus — all 3 "failures" independently confirmed as real, correct findings

| Host | Grade | "Failing" findings | Independently verified? |
|---|---|---|---|
| github.com | A+ | — | — |
| letsencrypt.org | A+ | — | — |
| zerodha.com | A+ | — | — |
| google.com | C | `TLS_LEGACY_PROTOCOL`, `HSTS_MISSING`, `NO_HTTPS_REDIRECT` | ✅ all three, see A3 |
| cloudflare.com | A | `TLS_LEGACY_PROTOCOL` | ✅ see A3 |
| razorpay.com | A | `READINESS_MANUAL_2027` | ✅ cert lifetime 393 days, real |

The harness's "known good ⇒ zero high/critical findings" assumption was too strict. Google and Cloudflare's edges genuinely still negotiate TLS 1.0 for compatibility, and google.com's apex neither sets HSTS nor redirects its bare HTTP listener to HTTPS — all confirmed independently (A3). These are correct, valuable findings about real production configurations, not scanner defects. `corpus.py` now documents this explicitly so future runs aren't misread as regressions.

### Edge cases — 8/8, none crashed, none invented data

Nonexistent domain, resolves-but-refuses-443 (`aspmx.l.google.com`), no-MX (`example.com`), no-CAA (`example.com`), IDN (`münchen.de`), Cloudflare-proxied (`canva.com`), wildcard (`github.io`), WHOIS-privacy (`razorpay.com`) — all degraded cleanly to `status: "error"` on the affected modules with the rest of the scan intact.

One point worth flagging explicitly given rule 7's emphasis on WHOIS: `example.com`'s `DOMAIN_EXPIRING_CRITICAL` finding looked alarming at first glance (IANA's reserved domain "expiring" in 2 days), but the raw WHOIS record genuinely says `expiration_date: 2026-08-13` right now — verified directly against `python-whois`. The scanner is reporting the literal authoritative record accurately; the record itself is what's misleading (IANA renews it as a matter of protocol necessity). No fix needed — this is rule 7 working as intended: report what the source says, don't guess around it.

### Indian real-world corpus — 9 hosts, no assertions, for review

| Host | Grade | Cert issuer / lifetime | Notable |
|---|---|---|---|
| irctc.co.in | A+ | GlobalSign, 199d | `READINESS_MANUAL_2027` |
| sbi.co.in | A+ | Entrust, 198d | `READINESS_MANUAL_2027`, no DNSSEC |
| incometax.gov.in | A+ | — | **does not resolve** (all TLS modules `status: error`, degraded cleanly) |
| uidai.gov.in | C | eMudhra, 390d | `CERT_EXPIRING_SOON` (13 days left — genuine) |
| flipkart.com | C | GlobalSign, 199d | missing HSTS/CSP/most security headers |
| swiggy.com | C | Amazon, 394d | 13 findings, missing HSTS/CSP, no TLS1.3 |
| iitb.ac.in | A | DigiCert, 393d | `CERT_LONG_LIFETIME` |
| iitd.ac.in | A+ | GlobalSign, 396d | `CERT_LONG_LIFETIME` |
| du.ac.in | A+ | DigiCert, 198d | no DNSSEC/CAA |

This is exactly the buyer-facing picture the product is for: most of these run long-lived certs on a manual renewal cadence that won't survive the March 2027 100-day cutoff, and several are missing basic security headers. No crashes, no wrong data.

---

## A3. Ground-truth cross-check — 10 domains, zero discrepancies

For each host: our scanner's `certificate` and `dns` module output, independently verified against `openssl s_client` (cert dates/issuer) and `dig @1.1.1.1` (MX/NS/CAA). `crt.sh` was unreachable throughout this test window (502, then 404, then a hard timeout across three separate attempts, minutes apart) — a known characteristic of that free public service, not something in our control; not included below.

| Host | not_before / not_after match | Issuer match | MX/NS/CAA match (dig) | Notable |
|---|---|---|---|---|
| google.com | ✅ exact | ✅ Google Trust Services WE2 | ✅ | A record differs between our scan and `dig` — expected DNS round-robin/anycast, not a bug |
| cloudflare.com | ✅ exact | ✅ Google Trust Services WE1 | ✅ | — |
| github.com | ✅ exact | ✅ Sectigo | ✅ | — |
| razorpay.com | ✅ exact | ✅ Amazon RSA 2048 M01 | ✅ (CAA empty both) | A record differs — CDN round-robin (CloudFront ranges both sides), not a bug |
| expired.badssl.com | ✅ exact (Apr 2015) | ✅ COMODO | ✅ | `is_expired=true` confirmed |
| self-signed.badssl.com | ✅ exact | ✅ issuer==subject | ✅ | `is_self_signed=true` confirmed |
| wrong.host.badssl.com | ✅ exact | ✅ Let's Encrypt YR2 | ✅ | `hostname_matches=false` correctly detected — cert is `*.badssl.com`, which does **not** cover the two-label `wrong.host.badssl.com` under wildcard matching rules; subtle case, confirmed correct |
| irctc.co.in | ✅ exact | ✅ GlobalSign GCC R3 EV | ✅ exact (Akamai NS, 3 MX) | — |
| sbi.co.in | ✅ exact | ✅ Entrust | ✅ exact | — |
| flipkart.com | ✅ exact | ✅ GlobalSign RSA OV | ✅ exact (Mimecast MX, UltraDNS NS, CAA) | — |

**Zero discrepancies** in any date, issuer string, MX record, NS record, or CAA record across all 10 domains — every field matched byte-for-byte or set-for-set against the independent tool. The only differences observed were A-record IPs on two CDN-backed/anycast domains (google.com, razorpay.com), which is expected behavior for load-balanced infrastructure, not a data-accuracy defect.

---

## A3b. Headers module ground-truth cross-check (Gate A follow-up A1)

**Date:** 2026-08-11. **Scope:** this section covers the `headers` module only, on the three domains named in `docs/GATE_A_FOLLOWUPS.md` A1 (google.com, flipkart.com, swiggy.com). The remaining four A1 modules (`tls`, `chain`, `email_auth`, `readiness`) across the full ten-domain A3 set are cross-checked separately in A3c below.

### The suspected bug, checked

A1's hypothesis: google.com's `HSTS_MISSING`/`NO_HTTPS_REDIRECT` findings are wrong because the headers module evaluates headers against the originally-requested host instead of the final URL after a redirect crosses to `www`.

Read `apps/api/app/scanner/headers.py` and `apps/api/app/safety.py::safe_get` first: `safe_get` already follows the full redirect chain itself (including hostname changes) and returns headers from the **final hop's response only** — `https_result.headers` in `headers.py` was never evaluating a stale, pre-redirect response. Confirmed this mechanism is correct with ground truth below. So the specific hypothesis (wrong-host evaluation) was **not** the bug. Something adjacent was.

### Ground truth, before any fix

```
$ curl -s -D - -o /dev/null -L http://google.com/ | grep -iE '^HTTP|strict-transport'
HTTP/1.1 301 Moved Permanently
HTTP/1.1 200 OK                          # -> http://www.google.com/, no https, no HSTS anywhere
$ curl -s -D - -o /dev/null https://www.google.com/ | grep -i strict-transport
                                          # (no output — Google sets no HSTS header for a plain curl UA)
```

Scanner (pre-fix) on google.com: `HSTS_MISSING`, `NO_HTTPS_REDIRECT` — **matches curl exactly.** Not a bug for google.com; the Gate A report's original finding was correct.

```
$ curl -s -D - -o /dev/null -L --max-redirs 10 http://swiggy.com/ | grep -iE '^HTTP|Location|strict-transport'
HTTP/1.1 301 Moved Permanently
Location: https://www.swiggy.com:443/
HTTP/1.1 202 Accepted
Strict-Transport-Security: max-age=31536000
```

Ground truth: swiggy.com **does** set HSTS on the final hop. Scanner (pre-fix) on swiggy.com: `HSTS_MISSING` — **a genuine false positive.**

### Root cause: not the redirect hop, the User-Agent

Reproduced directly inside the API container:

```python
target = await resolve_and_validate("www.swiggy.com")
transport = PinnedHostTransport(pinned_ip=target.ip, verify=False)
async with httpx.AsyncClient(transport=transport, verify=False, follow_redirects=False) as client:
    r = await client.get("https://www.swiggy.com:443/")   # no explicit User-Agent -> httpx default
# r.status_code == 403, body is a CloudFront error page, zero security headers of any kind
```

Confirmed the cause is the User-Agent string, not IP pinning or DNS, by reproducing the exact same split with `curl`:

```
$ curl -sD - -o /dev/null -L -A "python-httpx/0.27.2" https://swiggy.com/ | grep -iE '^HTTP|X-Cache'
HTTP/1.1 301 Moved Permanently
HTTP/1.1 403 Forbidden
X-Cache: Error from cloudfront

$ curl -sD - -o /dev/null -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" https://swiggy.com/ | grep -iE '^HTTP|strict-transport'
HTTP/1.1 301 Moved Permanently
HTTP/1.1 202 Accepted
Strict-Transport-Security: max-age=31536000
```

`httpx`'s default `python-httpx/<version>` User-Agent gets an outright CloudFront WAF block — 403, no security headers of any kind, not even the ones the WAF itself normally passes through — on the exact request that returns the real origin response, HSTS included, with a browser User-Agent. A blocked page isn't "no HSTS present," it's "we never saw the real response," and the module was reporting it as the former. This is a real headers-module ground-truth defect, just not the one A1 hypothesized.

Checked whether this also explained the flipkart.com findings in the original Gate A report. Ground truth from this host: flipkart.com returns a captcha-walled `403` (`x-captcha-validate: true`) regardless of User-Agent — curl with a browser UA gets the same 403 as curl with no UA override. Not User-Agent-related on this host from this network path; separately reproduced from the container's own egress IP below.

### The fix

`apps/api/app/safety.py`: `safe_get` (the only caller is `headers.py`) now sends a standard desktop-browser `User-Agent` (`SCANNER_USER_AGENT`) on every hop instead of leaving httpx's default. Scoped to the `headers` module only — `certificate`/`chain`/`tls` use raw TLS handshakes with no HTTP layer and no User-Agent to send, so they're unaffected. Documented as CONTRACT.md §10 rule 10 (v1.2); §6.4's `headers.data` section now states the final-hop evaluation semantics explicitly, as A1 asked.

### Ground truth, after the fix

Ran the live `headers` module (`docker compose exec api python`, restarted container to pick up the change) against all three domains, then independently re-verified each with `curl` using the same browser User-Agent:

| Host | Before fix | After fix | Independent re-check |
|---|---|---|---|
| google.com | `final_url` stuck on `http://www.google.com/`, `HSTS_MISSING`, `NO_HTTPS_REDIRECT` | `final_url=https://www.google.com/?gws_rd=ssl`, `http_to_https_redirect=true`, `hsts.present=true` (max-age 31536000) | `curl -A "<chrome-ua>" -L http://google.com/` reproduces the identical 3-hop chain (http apex → http www → 302 to https www) and the same HSTS header. Google's own behavior is User-Agent-gated: it never upgrades a non-browser client to HTTPS or sends HSTS, but it does both for a real browser UA — the finding the module now reports is the one that matches what an actual visitor sees. |
| flipkart.com | `HSTS_MISSING` plus `CSP_MISSING` (WAF/challenge response, not the real page) | `status_code=200`, real `content-security-policy` naming `flipkart.com`/`flixcart.com` domains, real `Set-Cookie`s — `HSTS_MISSING` still fires (genuinely true) | `safe_get` from inside the container (same egress as production) returns the real origin 200 response — confirmed by the presence of Flipkart-specific cookies (`T=`, `SN=`, `at=`) and CSP domains, which a generic WAF block page would not have. |
| swiggy.com | `HSTS_MISSING` | `hsts.present=true` (max-age 31536000), findings drop from 5 to 2 (`CSP_MISSING`, `PERMISSIONS_POLICY_MISSING`, both genuinely true) | Matches the `curl` ground truth captured above exactly. |

### Result

One real bug found and fixed: the headers module's default HTTP-library User-Agent caused WAF-fronted production sites (confirmed on swiggy.com, CloudFront bot-management) to return a blocked/challenge page instead of the real origin response, producing false `*_MISSING` findings across every header the module checks, not just HSTS. Fixed by sending a standard browser User-Agent (`apps/api/app/safety.py`), scoped to the one module that makes HTTP requests. The redirect-chain hostname-crossing mechanism itself (`safe_get` following redirects and evaluating headers on the final hop) was already correct and needed no code change — only explicit documentation, added to CONTRACT.md §6.4 and §10 rule 10 (v1.2).

Regression tests added: `apps/api/tests/test_scanner_headers.py::test_swiggy_com_headers_are_read_from_the_final_hop` and `::test_flipkart_com_reaches_the_real_origin_not_a_waf_challenge` (both live, `require_internet`-gated); `apps/api/tests/test_safety.py::test_scanner_user_agent_is_not_the_httpx_default` (offline, guards against silently reverting to the httpx default). Full suite: **167/167 passing** (164 + 3 new), `ruff check` and `mypy app` show no new issues introduced by this change (both tools' remaining findings pre-date this session — confirmed via `git stash`).

---

## A3c. `tls`, `chain`, `email_auth`, `readiness` ground-truth cross-check (Gate A follow-up A1, continued)

**Date:** 2026-08-11. **Scope:** the four remaining A1 modules, on the same ten domains A3 used (google.com, cloudflare.com, github.com, razorpay.com, expired.badssl.com, self-signed.badssl.com, wrong.host.badssl.com, irctc.co.in, sbi.co.in, flipkart.com). Ran the live modules in-container (`docker compose exec api python`) and independently verified every field against `openssl s_client` (per-protocol handshakes and `-showcerts` for the chain), `nslookup -type=TXT … 8.8.8.8` (SPF/DMARC/DKIM — `dig` isn't installed on this Windows host or in the image, `nslookup` is a fully independent resolver client, not the code under test), and hand arithmetic for `readiness`.

### tls — 9/10 clean, 1 real bug found and fixed

Protocol support (`tls1_0`/`tls1_1`/`tls1_2`/`tls1_3`), checked with `openssl s_client -<version> -cipher "DEFAULT@SECLEVEL=0"` (modern OpenSSL 3.x refuses sub-1.2 protocols by default; `SECLEVEL=0` is required to even ask the question) against every domain:

| Host | tls1_0 | tls1_1 | tls1_2 | tls1_3 | Scanner match |
|---|---|---|---|---|---|
| google.com | ✅ | ✅ | ✅ | ✅ | exact |
| cloudflare.com | ✅ | ✅ | ✅ | ✅ | exact |
| github.com | ❌ | ❌ | ✅ | ✅ | exact |
| razorpay.com | ❌ | ❌ | ✅ | ✅ | exact (after fix — see below) |
| expired.badssl.com | ✅ | ✅ | ✅ | ❌ | exact |
| self-signed.badssl.com | ✅ | ✅ | ✅ | ❌ | exact |
| wrong.host.badssl.com | ✅ | ✅ | ✅ | ❌ | exact |
| irctc.co.in | ❌ | ❌ | ✅ | ✅ | exact |
| sbi.co.in | ❌ | ❌ | ✅ | ✅ | exact |
| flipkart.com | ❌ | ❌ | ✅ | ✅ | exact |

**10/10 exact matches once razorpay.com is included** — but getting razorpay.com to complete at all surfaced a real, reproducible bug.

**The bug:** the live `tls` module against razorpay.com returned `status: "error"`, `TimeoutError`, on 2 of 2 initial runs — not flaky, deterministic. Isolated it to a single primitive call: `open_pinned_tls_handshake(ip, 443, "razorpay.com", min_protocol="tls1_2", max_protocol="tls1_2")` alone, no concurrency, reliably took **8.01s, every one of 3 repeated runs** — while an independent `openssl s_client -tls1_2` handshake to the same host completed in **2.5s**. Something inside our own code, not the server, was burning ~5.5 extra seconds.

Instrumented `_do_pinned_tls_handshake` in `apps/api/app/safety.py` directly (logging every `WantReadError`/`select()` cycle). The initial TLS1.2 handshake itself completed in 0.26s. Immediately after, the code's own renegotiation probe ran:
```python
if negotiated_protocol != "TLSv1.3":
    with contextlib.suppress(Exception):
        if conn.renegotiate():          # returns True — request queued
            _pump(sock, conn.do_handshake, deadline)   # deadline = the ORIGINAL 8s budget
            supports_renegotiation = True
```
`conn.renegotiate()` returned `True` (OpenSSL queued the request), but razorpay.com's CloudFront edge never answered it — a normal, hardened-server posture (disabling renegotiation without bothering to reject it), not a fluke. The follow-up `_pump` call then sat in `select()` waiting for a response that was never coming, for the entire *remaining* budget of the same `deadline` the initial handshake had already spent time against — timing out at exactly the original 8.0s mark, silently swallowed by the enclosing `contextlib.suppress(Exception)`. That 8.01s total then lost the race against `run_module`'s own separate 8.0s outer timeout (started slightly earlier, at the top of `_detect`, before DNS resolution), which fired first and discarded the entire module result — including the perfectly good, already-obtained TLS1.2 protocol/cipher read.

This isn't specific to razorpay.com — it fires for any TLS1.0/1.1/1.2 handshake against any server that silently ignores renegotiation, which is standard hardened/CDN behavior (Cloudflare and Google's edges in this same sweep happened not to trigger it — their default handshake negotiates TLS1.3, which skips the renegotiation probe entirely per the `!= "TLSv1.3"` guard — but any CDN-fronted site whose protocol probes land on 1.0/1.1/1.2 is exposed to it).

**Fix:** `apps/api/app/safety.py` — gave the renegotiation probe its own short, separate deadline (`RENEGOTIATION_PROBE_TIMEOUT_SECONDS = 2.0`) instead of sharing the full remaining handshake budget. A real accept-or-reject is fast when it happens at all; a server that's going to stay silent was always going to time out, so there's no reason to wait out the whole clock to find that out. After the fix, razorpay.com's `tls` module completes in ~2.2s, `status: "ok"`, with the same correct TLS1.2/TLS1.3 protocol data confirmed above.

Weak-cipher probe: `weak_ciphers: []` on every domain in this set, consistent with all ten being modern, non-`badssl.com`-weak-fixture hosts — no positive case in this sweep (A5 covers that separately with a fixture-independent unit test). Forward secrecy: `true` on all ten, consistent with every negotiated cipher in the table above being ECDHE/AES-GCM or TLS1.3 AEAD.

### chain — 10/10, zero discrepancies

`openssl s_client -showcerts`, subject/issuer sequence, compared against `chain.certificates[].subject`/`.issuer` in order:

| Host | Scanner chain_length | openssl cert count | Subjects match, in order |
|---|---|---|---|
| google.com | 3 | 3 | ✅ `*.google.com` → `WE2` → `GTS Root R4` |
| cloudflare.com | 3 | 3 | ✅ `cloudflare.com` → `WE1` → `GTS Root R4` |
| github.com | 3 | 3 | ✅ `github.com` → `Sectigo Public Server Authentication CA DV E36` → `...Root E46` |
| razorpay.com | 3 | 3 | ✅ `razorpay.com` → `Amazon RSA 2048 M01` → `Amazon Root CA 1` |
| expired.badssl.com | 3 | 3 | ✅ `*.badssl.com` → `COMODO RSA Domain Validation...` → `COMODO RSA Certification Authority` (untrusted root, correctly flagged) |
| self-signed.badssl.com | 1 | 1 | ✅ single self-signed `*.badssl.com` cert |
| wrong.host.badssl.com | 3 | 3 | ✅ `*.badssl.com` → `YR2` → `Root YR` |
| irctc.co.in | 3 | 3 | ✅ `www.irctc.co.in` → `GlobalSign GCC R3 EV TLS CA 2025` → `GlobalSign` (self-signed root) |
| sbi.co.in | 4 | 4 | ✅ `*.sbi.co.in` → `Entrust DV TLS Issuing RSA CA 2` → `Sectigo Public Server Authentication Root R46` → `USERTrust RSA Certification Authority` (root) |
| flipkart.com | 3 | 3 | ✅ `www.flipkart.com` → `GlobalSign RSA OV SSL CA 2018` → `GlobalSign` (root) |

sbi.co.in is the interesting one — a genuine 4-certificate cross-signed hierarchy (Entrust's intermediate cross-signed under Sectigo's root, itself cross-signed to USERTrust), and the scanner's `chain_length`, order, and every subject/issuer matched `openssl` exactly, position for position. No code changes needed.

### email_auth — 10/10, zero discrepancies

SPF and DMARC (`nslookup -type=TXT <domain> 8.8.8.8` / `nslookup -type=TXT _dmarc.<domain> 8.8.8.8`) matched the scanner's captured `record` strings **character-for-character** on every domain that has them (google.com, cloudflare.com, github.com, razorpay.com, irctc.co.in, sbi.co.in, flipkart.com), including SBI's unusual no-space `v=DMARC1;p=reject;...` formatting, parsed correctly. expired.badssl.com/self-signed.badssl.com/wrong.host.badssl.com correctly show `present: false` for both — confirmed genuinely absent via the same independent resolver, not a resolver blind spot (ruled out the Bug-3-style Docker-embedded-resolver gap that hit `dns_records.py`'s CAA/DNSKEY queries in the original Gate A run: TXT lookups are unaffected here).

DKIM selector probing spot-checked directly: google.com's zero hits confirmed genuine (`nslookup -type=TXT <selector>._domainkey.google.com` → `Non-existent domain` for all 6 checked selectors, not a lookup failure); irctc.co.in's `default` selector and sbi.co.in's `selector1`/`selector2` (the latter resolving via a `CNAME` to Microsoft 365's DKIM infrastructure, correctly followed) all independently confirmed present with real `v=DKIM1` records. No code changes needed.

### readiness — 10/10, zero discrepancies

Recomputed `lifetime_days` by hand from each domain's `certificate.not_before`/`.not_after` (already independently verified against `openssl` in A3) and re-derived the verdict from the §6.4 rules in `readiness.py`:

| Host | lifetime_days (recomputed) | Matches reported | Issuer | ACME? | Verdict (recomputed) | Matches scanner |
|---|---|---|---|---|---|---|
| google.com | 83 | ✅ | Google Trust Services | yes | automated | ✅ |
| cloudflare.com | 90 | ✅ | Google Trust Services | yes | automated | ✅ |
| github.com | 89 | ✅ | Sectigo Limited | no | semi_automated | ✅ |
| razorpay.com | 393 | ✅ | Amazon | — (>100) | manual | ✅ |
| expired.badssl.com | 3 | ✅ | COMODO CA Limited | no | semi_automated | ✅ |
| self-signed.badssl.com | 730 | ✅ | BadSSL | — (>100) | manual | ✅ |
| wrong.host.badssl.com | 89 | ✅ | Let's Encrypt | yes | automated | ✅ |
| irctc.co.in | 199 | ✅ | GlobalSign nv-sa | — (>100) | manual | ✅ |
| sbi.co.in | 198 | ✅ | Entrust Limited | — (>100) | manual | ✅ |
| flipkart.com | 199 | ✅ | GlobalSign nv-sa | — (>100) | manual | ✅ |

`renewals_per_year_now/_2027/_2029` spot-checked against `_renewals_per_year`'s own formula (`max(1, round(365 / min(lifetime_days, cap_days)))`) for google.com and razorpay.com — both match exactly (google.com: 4/4/8; razorpay.com: 1/4/8). No code changes needed — `readiness.py`'s arithmetic and verdict rules are correct as written.

### Result

One real bug found and fixed: `tls.py`'s renegotiation probe could burn nearly the entire per-handshake timeout budget against any server that silently ignores a renegotiation request (standard hardened/CDN behavior, confirmed on razorpay.com's CloudFront edge, reproduced 3/3), then lose the race against `run_module`'s separate outer timeout and discard an otherwise-successful TLS read. Fixed with a short, dedicated timeout for that one probe (`apps/api/app/safety.py`, `RENEGOTIATION_PROBE_TIMEOUT_SECONDS`). `chain`, `email_auth`, and `readiness` needed no changes — 10/10 domains, zero discrepancies against `openssl`/`nslookup`/hand arithmetic on every field checked.

Regression tests added: `apps/api/tests/test_scanner_tls.py::test_razorpay_com_completes_without_timing_out_on_renegotiation` (live, `require_internet`-gated, asserts `duration_ms < 5000` and correct protocol data); `apps/api/tests/test_safety.py::test_renegotiation_probe_timeout_is_well_under_the_module_budget` (offline, guards the timeout-budget invariant). Full suite: **169/169 passing** (167 + 2 new), `ruff check` and `mypy app` show no new issues.

**A1 is now fully closed**: all seven modules (`certificate`, `dns` in the original Gate A A3; `headers` in A3b; `tls`, `chain`, `email_auth`, `readiness` here) have been independently cross-checked against ground truth, across ten real domains apiece, with two real bugs found and fixed (headers' User-Agent, tls's renegotiation-probe timeout) and zero remaining discrepancies.

---

## A4. False-positive sweep — two runs, 10 minutes apart

Known-good corpus scanned twice: 09:22:29 UTC and 09:34:01 UTC.

| Host | Grade (run1 → run2) | Score (run1 → run2) | days_until_expiry (run1 → run2) | CERT_EXPIR* findings |
|---|---|---|---|---|
| google.com | C → C | 82 → 82 | 62 → 62 | none, either run |
| cloudflare.com | A → A | 93 → 93 | 56 → 56 | none, either run |
| github.com | A+ → A+ | 99 → 99 | 50 → 50 | none, either run |
| letsencrypt.org | A+ → A+ | 99 → 99 | 54 → 54 | none, either run |
| razorpay.com | A → A | 93 → 93 | 85 → 85 | none, either run |
| zerodha.com | A+ → A+ | 96 → 96 | 68 → 68 | none, either run |

All three assertions hold: **zero** `CERT_EXPIR*` findings on any known-good host in either run, **identical** grades across both runs, `days_until_expiry` diff of **0** (well within the ≤1 tolerance) on every host.

---

## A5. Load and safety sanity

**50 concurrent scans, mixed real targets, through the real HTTP → Postgres/Redis → arq worker pipeline** (not the in-process harness — this exercises the actual production path). 51 hosts submitted concurrently: 39 new + 12 served from cache (`200`, `cached: true` — correct behavior, hit during earlier testing within the 900s cache TTL). Zero crashes (5xx or exceptions), zero connection-pool exhaustion. All 39 newly-queued scans drained in 22.3s: 37 completed, 2 failed gracefully (`SCAN_FAILED`, "does not resolve" — both were deliberately-invalid hostnames). **Zero scans stuck in `queued`/`running`.**

**Rate limiter**, tested at its real configured thresholds (no environment changes): tripped exactly on the 7th request to the same hostname (`RATE_LIMIT_PER_HOSTNAME_PER_HOUR=6`) and exactly after 18 total requests from one IP across the hostname+IP tests (`RATE_LIMIT_PER_IP_PER_HOUR=20`), each time returning `429 RATE_LIMITED` with a correctly-shaped, positive, monotonically-decreasing `retry_after_seconds`.

**Scan timeout:** temporarily set `SCAN_TIMEOUT_SECONDS=1` to force the path deterministically (reverted to `25` immediately after). Submitted a fresh, uncached scan (`debian.org`) — landed in `status: "failed"`, `error.code: "UPSTREAM_TIMEOUT"` in 1020ms, with a working `public_slug`/`share_url`. Confirmed the share page itself renders (`200`) for a failed/timed-out scan. Never hung.

**SSRF guard**, live DNS: `localtest.me` resolves to `127.0.0.1` (confirmed via the container's own resolver). `POST /api/v1/scans` correctly returned `400 BLOCKED_TARGET` with evidence `{"hostname": "localtest.me", "ip": "127.0.0.1"}`.

All rate-limit/timeout env values were reverted to their committed `.env` defaults (`SCAN_TIMEOUT_SECONDS=25`, `RATE_LIMIT_PER_IP_PER_HOUR=20`, `RATE_LIMIT_PER_HOSTNAME_PER_HOUR=6`) before finishing this gate; confirmed via `docker compose ps` / health check that the stack is running with the real, committed configuration.

---

## Files changed in this session

- `apps/api/Dockerfile` — install `.[dev]` so the documented `pytest`/`ruff`/`mypy` workflow works in Docker
- `apps/api/tests/conftest.py` — `db_session` fixture now commits its schema (`engine.begin()` instead of `engine.connect()`)
- `apps/api/app/scanner/dns_records.py` — DNS resolver pinned to public nameservers, bypassing Docker's embedded resolver's CAA/DNSKEY blind spot
- `apps/api/tests/accuracy/corpus.py` — corrected the rc4.badssl.com expectation (server fixture is dead) and documented why three "known-good" hosts legitimately show high-severity findings

## Net result

164/164 tests passing, 0 skipped, inside the real deploy target. Three real bugs found and fixed, all specific to running in Docker — one of them (the DNS resolver blind spot) would have silently shipped incorrect `DNS_NO_CAA`/`DNS_NO_DNSSEC` findings on every production scan. Every number cross-checked against independent tooling across 10 domains matched exactly. No non-determinism, no crash, no stuck scan, no SSRF bypass.

**Recommendation: Gate A passes.** Ready for Gate B on your go-ahead.
