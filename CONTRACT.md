# SUN-DRAM Scanner — Engineering Contract v1.0

**Status:** LOCKED. This file is the single source of truth for every AI session working on this repo.

**Rule zero:** If a coding session is about to write something that contradicts this file, it must stop and say so instead of inventing an alternative. Contracts are amended by a human, never by a coding session.

**How to use this file:** Paste this entire document as the first message of every new coding chat, before the phase prompt. No exceptions.

---

## 1. What we are building

A hosted service that tells small and mid-sized teams whether their TLS certificates, DNS, and web security posture will survive the CA/Browser Forum lifetime reductions (200 days now, 100 days from 15 March 2027, 47 days from 2029), and then fixes it for them.

Phase 1 is the free public scanner: enter a hostname, get a graded report, share the link.

**Product name:** SUN-DRAM Scanner
**Repo root:** `D:\Scanner`
**Primary market:** India (₹ pricing, IST display, DPDP framing). Secondary: global (USD).

---

## 2. Non-negotiable rules

These exist to stop frontend and backend drifting apart across separate chat sessions.

1. **JSON is `snake_case` everywhere.** Backend emits `snake_case`; the TypeScript types mirror it exactly. No camelCase conversion layer, no serializer aliasing. `days_until_expiry` is `days_until_expiry` in Python, in JSON, and in TSX.
2. **The backend computes, the frontend renders.** All grades, scores, severities, verdicts, countdowns, and human-readable strings are produced by the API. The frontend never recalculates a grade, never derives a severity, never computes days-until-expiry from a timestamp. If the frontend needs a sentence, the API returns that sentence.
3. **Timestamps are ISO 8601 UTC with a `Z` suffix.** Example: `2026-08-09T10:14:03Z`. Durations are integers in milliseconds, suffixed `_ms`. Day counts are integers, suffixed `_days`. Never send local time. Never send a naive datetime.
4. **All identifiers are strings.** `scan_id` is a UUIDv4 string. Never an integer, never a raw UUID object.
5. **The API is versioned in the path.** Everything lives under `/api/v1`. Breaking a v1 response shape requires a contract amendment.
6. **Every enum value in section 5 is closed.** A coding session may not add a new status, severity, grade, or finding code without adding it to this file first.
7. **Every error uses the envelope in section 7.** No bare strings, no HTML error pages from the API.
8. **No secrets in code.** Everything configurable comes from environment variables named in section 4.
9. **Nothing is generated that the contract doesn't define.** If a field is needed and missing here, the session must flag it as `CONTRACT GAP:` in its response instead of quietly adding it.
10. **Every file a session produces is complete.** No `# ... rest of the file unchanged`, no elisions, no placeholder bodies.

---

## 3. Stack and repo layout

### 3.1 Stack (locked)

| Layer | Choice | Version floor |
|---|---|---|
| Backend | Python + FastAPI | 3.12 / FastAPI 0.115 |
| Validation | Pydantic v2 | 2.9 |
| Database | PostgreSQL | 16 |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | — |
| Queue / cache | Redis + `arq` | Redis 7 |
| Frontend | Next.js App Router + TypeScript | Next 15, TS 5.6 |
| Styling | Tailwind CSS | v4 |
| UI primitives | shadcn/ui (Radix) | — |
| Package manager (web) | pnpm | 9 |
| Local orchestration | Docker Compose | — |
| Testing | pytest (api), Vitest + Playwright (web) | — |
| Lint / format | ruff + mypy (api), eslint + prettier (web) | — |

Do not introduce another framework, ORM, state library, CSS system, or component kit. No Redux, no MUI, no Bootstrap, no Prisma, no Django.

### 3.2 Repo layout (locked)

```
Scanner/
├── CONTRACT.md                  # this file
├── ROADMAP.md
├── docker-compose.yml
├── .env.example
├── README.md
├── apps/
│   ├── api/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── migrations/
│   │   └── app/
│   │       ├── main.py           # FastAPI app factory, router mounting
│   │       ├── config.py         # pydantic-settings, reads env
│   │       ├── db.py             # engine, session
│   │       ├── models.py         # SQLAlchemy tables
│   │       ├── schemas.py        # Pydantic response models (mirrors §6)
│   │       ├── enums.py          # every enum in §5
│   │       ├── findings.py       # the finding catalogue in §8
│   │       ├── grading.py        # the scoring algorithm in §9
│   │       ├── errors.py         # error envelope + exception handlers
│   │       ├── ratelimit.py
│   │       ├── safety.py         # SSRF / private-address guard (§10)
│   │       ├── routers/
│   │       │   ├── health.py
│   │       │   ├── scans.py
│   │       │   └── meta.py
│   │       ├── scanner/
│   │       │   ├── orchestrator.py
│   │       │   ├── certificate.py
│   │       │   ├── chain.py
│   │       │   ├── tls.py
│   │       │   ├── dns_records.py
│   │       │   ├── email_auth.py
│   │       │   ├── headers.py
│   │       │   └── readiness.py
│   │       └── worker.py         # arq worker entrypoint
│   │   └── tests/
│   └── web/
│       ├── package.json
│       ├── Dockerfile
│       ├── next.config.ts
│       ├── tailwind.config.ts
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── page.tsx                    # landing + scan box
│       │   ├── scan/[slug]/page.tsx        # result page
│       │   ├── countdown/page.tsx
│       │   ├── docs/findings/[code]/page.tsx
│       │   └── api-status/page.tsx
│       ├── components/
│       │   ├── ui/                         # shadcn generated only
│       │   ├── scan/                       # ScanForm, GradeDial, ValidityBar, ModuleCard, FindingRow
│       │   └── layout/
│       ├── lib/
│       │   ├── api.ts                      # the ONLY place fetch() is called
│       │   └── format.ts
│       └── types/
│           └── contract.ts                 # hand-written mirror of §5 and §6
└── docs/
    └── findings/                           # markdown, one per finding code
```

**`apps/web/types/contract.ts` and `apps/api/app/schemas.py` must stay in lockstep.** Any change to one requires the same change to the other in the same session.

---

## 4. Environment variables (locked names)

```
# --- shared ---
APP_ENV=development                 # development | staging | production
LOG_LEVEL=info

# --- api ---
API_HOST=0.0.0.0
API_PORT=8000
DATABASE_URL=postgresql+psycopg://scanner:scanner@postgres:5432/scanner
REDIS_URL=redis://redis:6379/0
CORS_ORIGINS=http://localhost:3000
SCAN_TIMEOUT_SECONDS=25
SCAN_CACHE_TTL_SECONDS=900
RATE_LIMIT_PER_IP_PER_HOUR=20
RATE_LIMIT_PER_HOSTNAME_PER_HOUR=6
PUBLIC_BASE_URL=http://localhost:3000
ADMIN_TOKEN=                        # Gate B: gates GET /api/v1/admin/stats. Empty = endpoint always 403.
SENTRY_DSN=                         # Gate C: error tracking (api + worker). Empty = Sentry never initialised.
SESSION_SECRET=                     # Phase 2 §7.6: signs the session cookie. Not named by the phase prompt — name/mechanism signed off by the human 2026-08-14 (see §14 v2.1).
RESEND_API_KEY=                     # Phase 2 Step 2. CONTRACT GAP — see amendment 2.1: OTP delivery needs a real provider before Step 5's own app/notify/email.py is built. Empty = OTP codes are logged, not emailed.
EMAIL_FROM_ADDRESS=                 # Phase 2 Step 2. Paired with RESEND_API_KEY above; both required to actually send.
SCHEDULER_MAX_CONCURRENT_SCANS=3    # Phase 2 Step 4: caps concurrent scheduler-enqueued scans (§7.9) via a Redis semaphore, well under the worker's max_jobs of 10.
RAZORPAY_KEY_ID=                    # Phase 2 Step 6 (§7.11). INR checkout/webhooks. Empty = Razorpay checkout refuses with INTERNAL_ERROR rather than silently pretending to work.
RAZORPAY_KEY_SECRET=                # Paired with RAZORPAY_KEY_ID — Basic-auth credential for every Razorpay API call (app/billing/providers.py).
RAZORPAY_WEBHOOK_SECRET=            # HMAC-SHA256 key verifying X-Razorpay-Signature on POST /api/v1/billing/webhooks/razorpay.
STRIPE_SECRET_KEY=                  # Phase 2 Step 6 (§7.11). USD checkout/webhooks. Empty = Stripe checkout refuses with INTERNAL_ERROR the same way.
STRIPE_WEBHOOK_SECRET=              # Verifies the Stripe-Signature header on POST /api/v1/billing/webhooks/stripe.

# --- web ---
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_SENTRY_DSN=             # Gate C: error tracking (browser/server/edge). Empty = Sentry never initialised.
```

The frontend reads exactly one API variable: `NEXT_PUBLIC_API_BASE_URL`. It never hardcodes a URL.

---

## 5. Enums (closed sets)

Defined once in `apps/api/app/enums.py` and mirrored in `apps/web/types/contract.ts`.

```
ScanStatus        = "queued" | "running" | "completed" | "failed"
ModuleStatus      = "ok" | "warn" | "fail" | "error" | "skipped"
Severity          = "critical" | "high" | "medium" | "low" | "info"
Grade             = "A+" | "A" | "B" | "C" | "D" | "E" | "F"
ModuleName        = "certificate" | "chain" | "tls" | "dns" | "email_auth" | "headers" | "readiness"
ReadinessVerdict  = "automated" | "semi_automated" | "manual" | "unknown"
LifetimePhase     = "pre_2026" | "phase_200" | "phase_100" | "phase_47"
SpfPolicy         = "none" | "neutral" | "softfail" | "fail" | "absent"
DmarcPolicy       = "none" | "quarantine" | "reject" | "absent"

// --- Phase 2 additions (v2.0) ---
UserRole          = "owner" | "admin" | "member"
PlanCode          = "free" | "watch" | "watch_pro" | "secure" | "compliance"
SubscriptionState = "trialing" | "active" | "past_due" | "cancelled" | "expired"
BillingProvider   = "razorpay" | "stripe"
BillingInterval   = "monthly" | "annual"
Currency          = "INR" | "USD"
AlertType         = "cert_expiry" | "domain_expiry" | "grade_regression" | "scan_failure" | "new_critical_finding"
AlertChannel      = "email"                 // single-value today so Phase 3 can add "whatsapp"/"slack" without a shape change
AlertState        = "pending" | "sent" | "failed" | "suppressed"
MonitorState      = "active" | "paused" | "quota_blocked" | "verification_pending"
OtpPurpose        = "login" | "email_change"
InvoiceState      = "open" | "paid" | "void" | "uncollectible"   // Not specified by the phase prompt's §1.1 enum list — mirrors Stripe's own state set. Signed off by the human 2026-08-14 (see §14 v2.1).
DigestMode        = "immediate" | "digest"   // Phase 2 Step 5. Not named by the phase prompt's §1.1 enum list — Organisation.digest_mode (§6.7) needs a closed set and "immediate or daily digest" (§Step 5) is exactly two values.
```

`overall_grade` and every module `grade` use the `Grade` set. Grade colours are fixed in section 12.

### 5.1 Plans — single source of truth, `app/plans.py` (Phase 2)

The API, the pricing page, and every quota check read prices and limits from `app/plans.py` — never a hardcoded number in a handler or a component.

| Code | ₹/mo | $/mo | Hostnames | Scan interval | Alert lead days | Members |
|---|---|---|---|---|---|---|
| `free` | 0 | 0 | 3 | 24h | 14, 3 | 1 |
| `watch` | 999 | 29 | 25 | 6h | 60, 30, 14, 7, 3, 1 | 3 |
| `watch_pro` | 2999 | 79 | 100 | 6h | 60, 30, 14, 7, 3, 1 | 10 |

`secure` and `compliance` exist in `PlanCode` and in the pricing table today, but are **not purchasable** in Phase 2 — checkout returns a "contact us" path for them. Their features (sidecar, auto-TLS, compliance evidence packs) are Phase 3+ and must not be built now.

Annual billing is monthly rate × 12 × 0.7 (30% off). Surfaced prominently at checkout — cash today is worth more than ARPA later.

---

## 6. Data shapes

### 6.1 `Scan` — the complete response object

```jsonc
{
  "scan_id": "8f1c2b4e-9c7a-4a1e-8a1b-2f4d5e6a7b8c",
  "public_slug": "k3Xm9Qa2Rt7Z",
  "hostname": "example.com",
  "port": 443,
  "status": "completed",
  "created_at": "2026-08-09T10:14:03Z",
  "started_at": "2026-08-09T10:14:04Z",
  "completed_at": "2026-08-09T10:14:09Z",
  "duration_ms": 5120,
  "cached": false,

  "overall_grade": "C",
  "overall_score": 71,
  "headline": "This certificate expires in 12 days and the chain is incomplete.",
  "share_url": "http://localhost:3000/scan/k3Xm9Qa2Rt7Z",

  "counts": { "critical": 0, "high": 2, "medium": 3, "low": 1, "info": 4 },

  "modules": {
    "certificate": { /* ModuleResult */ },
    "chain":       { /* ModuleResult */ },
    "tls":         { /* ModuleResult */ },
    "dns":         { /* ModuleResult */ },
    "email_auth":  { /* ModuleResult */ },
    "headers":     { /* ModuleResult */ },
    "readiness":   { /* ModuleResult */ }
  },

  "findings": [ /* Finding[] — flattened, sorted by severity then module */ ],

  "error": null
}
```

Rules:
- `modules` always contains all seven keys, even when a module errored (`status: "error"`, `data: null`).
- `findings` is the flat, sorted list. Each module's own `findings` array is a subset. Duplication is intentional — the frontend uses whichever is convenient.
- While `status` is `queued` or `running`, `modules` values may be `null`, and `overall_grade`, `overall_score`, `headline`, `counts` are `null`.
- `error` is `null` unless `status == "failed"`, in which case it holds an `ApiError` object (section 7).

### 6.2 `ModuleResult` — uniform wrapper for all seven modules

```jsonc
{
  "module": "certificate",
  "status": "warn",
  "score": 74,
  "grade": "C",
  "label": "Certificate",
  "summary": "Valid certificate from Let's Encrypt, expiring in 12 days.",
  "checked_at": "2026-08-09T10:14:06Z",
  "duration_ms": 820,
  "findings": [ /* Finding[] */ ],
  "data": { /* module-specific, see 6.4 */ },
  "error": null
}
```

`label` and `summary` are backend-authored display strings. The frontend prints them as-is.

### 6.3 `Finding`

```jsonc
{
  "code": "CERT_EXPIRING_SOON",
  "module": "certificate",
  "severity": "high",
  "title": "Certificate expires in 12 days",
  "description": "The certificate for example.com is valid until 21 August 2026. Renewal usually needs to happen before day 30 to leave room for failure.",
  "remediation": "Set up automated renewal, or renew now and add an expiry alert at 30, 14 and 7 days.",
  "evidence": { "days_until_expiry": 12, "not_after": "2026-08-21T09:00:00Z" },
  "docs_path": "/docs/findings/cert-expiring-soon"
}
```

- `code` is `SCREAMING_SNAKE_CASE`, unique, and listed in section 8.
- `docs_path` is `/docs/findings/` + the code lowercased with underscores turned into hyphens.
- `evidence` is a free-form object. The frontend may render it as a key/value table but must not depend on specific keys.

### 6.4 Module `data` payloads

**`certificate.data`**
```jsonc
{
  "subject_common_name": "example.com",
  "subject_alternative_names": ["example.com", "www.example.com"],
  "issuer_common_name": "R11",
  "issuer_organization": "Let's Encrypt",
  "serial_number": "03:9a:...",
  "fingerprint_sha256": "a1b2...",
  "not_before": "2026-05-23T09:00:00Z",
  "not_after": "2026-08-21T09:00:00Z",
  "lifetime_days": 90,
  "days_until_expiry": 12,
  "is_expired": false,
  "is_not_yet_valid": false,
  "is_self_signed": false,
  "is_wildcard": false,
  "hostname_matches": true,
  "key_algorithm": "ECDSA",
  "key_size_bits": 256,
  "signature_algorithm": "sha256WithRSAEncryption",
  "ocsp_stapling": false,
  "sct_count": 2
}
```

**`chain.data`**
```jsonc
{
  "chain_length": 2,
  "is_complete": true,
  "order_valid": true,
  "trusted_root": "ISRG Root X1",
  "certificates": [
    { "position": 0, "role": "leaf", "subject": "example.com", "issuer": "R11", "not_after": "2026-08-21T09:00:00Z" }
  ]
}
```
`role` is one of `"leaf" | "intermediate" | "root"`.

**`tls.data`**
```jsonc
{
  "protocols": {
    "tls1_0": { "supported": false, "deprecated": true },
    "tls1_1": { "supported": false, "deprecated": true },
    "tls1_2": { "supported": true,  "deprecated": false },
    "tls1_3": { "supported": true,  "deprecated": false }
  },
  "negotiated_protocol": "TLSv1.3",
  "negotiated_cipher": "TLS_AES_256_GCM_SHA384",
  "weak_ciphers": [],
  "forward_secrecy": true,
  "supports_renegotiation": false,
  "key_exchange": { "type": "ECDHE", "bits": 256, "curve": "X25519" }
}
```
`key_exchange` (v1.4, Gate A follow-up A2): every field nullable when not determinable. `type` comes from the negotiated cipher suite name and is reliable for TLS ≤ 1.2; TLS 1.3 suite names don't encode it, so `type` is `null` there. `bits`/`curve` require reading the negotiated DH/ECDHE group, which this stack's TLS library (pyOpenSSL) has no public getter for — confirmed by direct introspection of its bound OpenSSL bindings, not assumed — so they are `null` in every live scan today. Never guessed (§10): `TLS_WEAK_KEY_EXCHANGE` (§8) only fires when `bits` is actually known.

**`dns.data`**
```jsonc
{
  "a_records": ["93.184.216.34"],
  "aaaa_records": [],
  "cname": null,
  "nameservers": ["ns1.example.net"],
  "mx_records": [{ "priority": 10, "host": "mail.example.com" }],
  "caa_records": ["0 issue \"letsencrypt.org\""],
  "caa_present": true,
  "dnssec_enabled": false,
  "registrar": "GoDaddy.com, LLC",
  "domain_created_at": "2015-03-01T00:00:00Z",
  "domain_expires_at": "2027-03-01T00:00:00Z",
  "days_until_domain_expiry": 204
}
```
Any field may be `null` when the lookup is unavailable (WHOIS often is). `null` means unknown, never zero.

**`email_auth.data`**
```jsonc
{
  "spf": { "present": true, "record": "v=spf1 include:_spf.google.com ~all", "policy": "softfail", "lookup_count": 4, "issues": [] },
  "dmarc": { "present": true, "record": "v=DMARC1; p=none;", "policy": "none", "pct": 100, "rua_present": false },
  "dkim": { "selectors_checked": ["default", "google", "selector1", "selector2", "k1", "mail"], "selectors_found": ["google"] }
}
```
DKIM is best-effort selector probing. `selectors_found: []` produces an `info` finding, never a `fail`.

**`headers.data`**
```jsonc
{
  "final_url": "https://example.com/",
  "status_code": 200,
  "redirect_chain": ["http://example.com/", "https://example.com/"],
  "http_to_https_redirect": true,
  "hsts": { "present": true, "max_age_seconds": 31536000, "include_subdomains": true, "preload": false },
  "content_security_policy": { "present": false, "value": null },
  "x_content_type_options": { "present": true, "value": "nosniff" },
  "x_frame_options": { "present": false, "value": null },
  "referrer_policy": { "present": true, "value": "strict-origin-when-cross-origin" },
  "permissions_policy": { "present": false, "value": null },
  "server_header": "nginx",
  "missing": ["content_security_policy", "x_frame_options", "permissions_policy"]
}
```
Redirect-chain semantics (v1.2): the `headers` module makes two probes — an HTTP probe starting at `http://{hostname}/` and an HTTPS probe starting at `https://{hostname}/` — and follows redirects on each, up to §10 rule 4's cap, revalidating every hop. When a redirect crosses to a different hostname (the common `example.com` → `www.example.com` case), every header field in this payload — `hsts`, `content_security_policy`, every other presence field, `server_header`, `missing` — is evaluated on the **final hop's response**, not the originally-requested host. `final_url` always names that final hop, so the response makes the substitution visible instead of hiding it. `http_to_https_redirect` is `true` only when the HTTP probe's own chain ends on an `https://` URL. A blocked or challenge response (a WAF/bot-management page, not the real origin) is a fetch failure the module cannot distinguish from a genuine missing header from response headers alone — see §10 rule 10 on the User-Agent it sends to reduce this — but a request-level exception (timeout, connection refused, TLS failure) still produces `status: "error"` per §6.2, never a confident `false`.

**`readiness.data`** — the product's signature output
```jsonc
{
  "current_lifetime_days": 90,
  "current_phase": "phase_200",
  "phase_label": "200-day maximum (in force since 15 March 2026)",
  "next_deadline": "2027-03-15",
  "days_until_next_deadline": 218,
  "renewals_per_year_now": 4,
  "renewals_per_year_2027": 4,
  "renewals_per_year_2029": 8,
  "verdict": "automated",
  "verdict_label": "Looks automated",
  "verdict_reason": "A 90-day Let's Encrypt certificate reissued recently is consistent with an automated ACME client.",
  "survives_2027": true,
  "survives_2029": true,
  "message": "This hostname is already on a short-lifetime automated cadence and will not be affected by the March 2027 change."
}
```

Verdict inference rules (backend, deterministic):
- `lifetime_days <= 100` **and** issuer is a known ACME CA (Let's Encrypt, ZeroSSL, Google Trust Services, Buypass) → `automated`
- `lifetime_days <= 100` and issuer unknown → `semi_automated`
- `lifetime_days > 100` → `manual`
- certificate module errored → `unknown`

### 6.5 `MetaDeadlines` — `GET /api/v1/meta/deadlines`

```jsonc
{
  "generated_at": "2026-08-09T10:14:03Z",
  "phases": [
    { "phase": "phase_200", "effective_from": "2026-03-15", "max_lifetime_days": 200, "dcv_reuse_days": 200, "renewals_per_year": 2, "active": true },
    { "phase": "phase_100", "effective_from": "2027-03-15", "max_lifetime_days": 100, "dcv_reuse_days": 100, "renewals_per_year": 4, "active": false },
    { "phase": "phase_47",  "effective_from": "2029-03-15", "max_lifetime_days": 47,  "dcv_reuse_days": 10,  "renewals_per_year": 8, "active": false }
  ],
  "next_deadline": { "phase": "phase_100", "date": "2027-03-15", "days_remaining": 218 }
}
```

These dates are hardcoded constants in `app/scanner/readiness.py`. `days_remaining` is computed server-side at request time.

### 6.6 `User` (Phase 2)

```jsonc
{
  "user_id": "3a1c...",
  "email": "founder@example.com",
  "email_verified": true,
  "created_at": "2026-08-09T10:14:03Z",
  "last_login_at": "2026-08-09T10:14:03Z"   // nullable — null until first successful OTP verify
}
```

No password field exists anywhere in this shape or the database — email OTP only (§7.6). There is nothing to hash, store, or breach.

### 6.7 `Organisation` (Phase 2)

```jsonc
{
  "org_id": "3a1c...",
  "name": "Acme Inc",
  "country": "IN",           // ISO 3166-1 alpha-2, set at signup, drives billing provider selection (§Step 6)
  "currency": "INR",         // Currency
  "plan_code": "free",       // PlanCode
  "timezone": "Asia/Kolkata",       // IANA zone name (§Step 5). Default for every org, no setup endpoint exists yet (Step 7)
  "quiet_hours_start": "21:00",     // "HH:MM", 24-hour, local to `timezone`
  "quiet_hours_end": "08:00",       // wraps midnight when start > end, as it does by default
  "digest_mode": "digest",          // DigestMode. "digest" for every org today — all orgs are created on the free plan (§Step 5: "digest on free, immediate on paid")
  "digest_hour": 9,                 // 0-23, local to `timezone` — the hour a daily digest sends
  "created_at": "2026-08-09T10:14:03Z"
}
```

Created automatically as a personal org on first OTP login (§7.6). The five alert-preference fields were added in Step 5 (v2.0's amendment note flagged them as this step's own concern, not invented ahead of it) — every org gets a working default the day it's created; no endpoint changes them yet (Step 7's `/app/alerts` settings page).

### 6.8 `Membership` (Phase 2)

```jsonc
{
  "org_id": "3a1c...",
  "user_id": "3a1c...",
  "role": "owner",           // UserRole
  "invited_by": null,        // uuid, nullable — null for the org's creator, otherwise the inviting user's id
  "joined_at": "2026-08-09T10:14:03Z"
}
```

### 6.9 `MonitoredHostname` (Phase 2)

```jsonc
{
  "monitor_id": "3a1c...",
  "org_id": "3a1c...",
  "hostname": "example.com",
  "port": 443,
  "state": "active",             // MonitorState
  "label": "Production",         // nullable
  "notes": null,                 // nullable
  "last_scan_id": "8f1c...",     // nullable — null before the first scheduled scan runs
  "last_grade": "A+",            // Grade, nullable
  "last_score": 97,              // nullable
  "last_scanned_at": "2026-08-09T10:14:03Z",  // nullable
  "next_scan_at": "2026-08-09T16:14:03Z",     // nullable — null when state is not "active"
  "days_until_expiry": 88,       // nullable
  "created_at": "2026-08-09T10:14:03Z"
}
```

Reuses §7.2 hostname normalisation and §10 safety guard unchanged — no parallel validation path for monitored hostnames.

### 6.10 `AlertRecipient` (Phase 2)

```jsonc
{
  "recipient_id": "3a1c...",
  "org_id": "3a1c...",
  "monitor_id": null,        // uuid, nullable — null means org-wide (every monitor), non-null scopes to one monitor
  "email": "ops@example.com",
  "verified": true,
  "created_at": "2026-08-09T10:14:03Z"
}
```

Backing table exists as of Step 5 (`alert_recipients`) and the alert engine (§7.10) resolves and delivers against whatever rows are in it. Step 7 (§7.12) is the first to add endpoints that create/list/delete them, for the `/app/alerts` settings page ("suggest a role address" is UI copy for that page, not backend logic). Until an org has added any, every `owner`/`admin` membership's email is used as a fallback, so alerts are never silently dropped for lack of a recipient.

### 6.11 `AlertEvent` (Phase 2)

```jsonc
{
  "alert_id": "3a1c...",
  "org_id": "3a1c...",
  "monitor_id": "3a1c...",
  "type": "cert_expiry",     // AlertType
  "state": "sent",           // AlertState
  "severity": "high",        // Severity (§5, reused unchanged)
  "subject": "example.com — certificate expires in 7 days",
  "dedupe_key": "3a1c...:cert_expiry:7",   // "{monitor_id}:{type}:{threshold}" — a key already in "sent" state never sends again (§Step 5)
  "scheduled_for": "2026-08-09T10:14:03Z",
  "sent_at": null,           // nullable — null until state becomes "sent"
  "recipients": ["ops@example.com"],
  "payload": {}               // object — template data for the email, shape is module/type-specific and not enumerated here
}
```

Gets its first Pydantic schema and JSON exposure in Step 7 (§7.12's `GET /monitors/{monitor_id}/alerts`) — Steps 4/5 only ever wrote this table, never serialised it.

Backing table exists since Step 4 (`scan_failure` only); Step 5 (§7.10) is what actually moves `state` through `pending` → `sent`/`suppressed`/`failed` for every `AlertType`, and is the first thing that ever populates `recipients`. No Pydantic schema or endpoint exists yet — still true after Step 5, since nothing serialises this to JSON until Step 7's `/app/alerts` dashboard reads it.

### 6.12 `Subscription` (Phase 2)

```jsonc
{
  "subscription_id": "3a1c...",
  "org_id": "3a1c...",
  "plan_code": "watch",              // PlanCode
  "provider": "razorpay",            // BillingProvider
  "interval": "monthly",             // BillingInterval
  "currency": "INR",                 // Currency
  "state": "active",                 // SubscriptionState
  "current_period_start": "2026-08-09T10:14:03Z",
  "current_period_end": "2026-09-09T10:14:03Z",
  "cancel_at_period_end": false,
  "provider_subscription_id": null   // nullable — null until the provider's checkout/webhook confirms it (§Step 6)
}
```

### 6.13 `Invoice` (Phase 2)

```jsonc
{
  "invoice_id": "3a1c...",
  "org_id": "3a1c...",
  "number": "INV-2026-000123",
  "amount_minor": 99900,     // integer, minor units (paise/cents) — NEVER a float, never a formatted string
  "currency": "INR",         // Currency
  "state": "paid",           // InvoiceState (§5)
  "issued_at": "2026-08-09T10:14:03Z",
  "paid_at": "2026-08-09T10:14:03Z",   // nullable
  "pdf_url": null,           // nullable string
  "gstin": null,              // nullable — customer-supplied GSTIN, India only
  "place_of_supply": null     // nullable — India tax field, captured now even though rate logic stays simple (retrofitting means reissuing invoices)
}
```

`amount_minor` + `currency` is the only money representation anywhere in this contract, Phase 2 onward — no exceptions, matching §2 rule 1's `snake_case` discipline: one shape, everywhere.

### 6.14 Paginated list envelope (Phase 2, every list endpoint)

```jsonc
{ "items": [], "page": 1, "per_page": 25, "total": 137, "has_more": true }
```

`page` defaults to `1`, `per_page` defaults to `25`. Maximum `per_page` is `100` — not specified by the phase prompt, signed off by the human 2026-08-14 (see §14 v2.1).

---

## 7. API surface (Phase 1)

Base path `/api/v1`. All responses `application/json`.

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/api/v1/health` | liveness + db/redis check | 200 |
| POST | `/api/v1/scans` | start a scan | 202 |
| GET | `/api/v1/scans/{scan_id}` | poll / fetch by id | 200 |
| GET | `/api/v1/scans/slug/{public_slug}` | fetch by shareable slug | 200 |
| GET | `/api/v1/meta/deadlines` | countdown data | 200 |
| POST | `/api/v1/waitlist` | capture an email against a scan (Gate B) | 200 |
| GET | `/api/v1/admin/stats` | plain-text usage counters, `?token=` gated (Gate B) — the one exception to "all responses `application/json`": this returns `text/plain`, since it's a page opened directly in a browser, not a shape the frontend consumes | 200 |

### 7.1 `POST /api/v1/scans`

Request:
```json
{ "hostname": "example.com", "port": 443 }
```
`port` is optional, defaults to `443`.

Response `202`:
```json
{
  "scan_id": "8f1c...",
  "public_slug": "k3Xm9Qa2Rt7Z",
  "status": "queued",
  "poll_url": "/api/v1/scans/8f1c...",
  "share_url": "http://localhost:3000/scan/k3Xm9Qa2Rt7Z",
  "cached": false
}
```

If a completed scan for the same hostname exists within `SCAN_CACHE_TTL_SECONDS`, return `200` with that scan's ids and `"cached": true`.

### 7.2 Hostname normalisation (backend, before anything else)

Applied in this order:
1. Trim whitespace, lowercase.
2. Strip scheme (`http://`, `https://`), path, query, fragment.
3. Strip a trailing dot.
4. Strip `:port` and use it as `port` if `port` was not supplied.
5. IDN → punycode via `idna`.
6. Validate: 1–253 chars, at least one dot, labels 1–63 chars matching `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`.

Failure → `400 INVALID_HOSTNAME`.

### 7.3 Polling contract

The frontend polls `GET /api/v1/scans/{scan_id}` every **1500 ms**, gives up after **90 s**, and stops immediately on `completed` or `failed`. The backend must respond in under 300 ms while a scan is running — it reads state, it does not block on the scan.

### 7.4 Error envelope

Every non-2xx response, without exception:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many scans from this address. Try again in 34 minutes.",
    "details": { "retry_after_seconds": 2040 },
    "request_id": "req_7f3a1c9e"
  }
}
```

Closed set of error codes and their HTTP statuses:

| Code | HTTP | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | request body fails schema |
| `INVALID_HOSTNAME` | 400 | normalisation rejected the input |
| `BLOCKED_TARGET` | 400 | private/reserved address or blocklisted host |
| `RATE_LIMITED` | 429 | per-IP or per-hostname limit hit; extended in Phase 2 to the per-monitor manual-rescan limit (§7.8) |
| `SCAN_NOT_FOUND` | 404 | unknown `scan_id` or `public_slug` |
| `SCAN_FAILED` | 200 | *not an HTTP error* — returned inside `Scan.error` |
| `UPSTREAM_TIMEOUT` | 504 | our own dependency timed out |
| `INTERNAL_ERROR` | 500 | anything else |
| `UNAUTHENTICATED` | 401 | no valid session cookie (Phase 2) |
| `FORBIDDEN` | 403 | authenticated, but the role doesn't permit this action (Phase 2) |
| `OTP_INVALID` | 400 | wrong code, or code already used (Phase 2) |
| `OTP_EXPIRED` | 400 | code past its 10-minute window (Phase 2) |
| `OTP_RATE_LIMITED` | 429 | too many OTP requests or verify attempts (Phase 2) |
| `QUOTA_EXCEEDED` | 402 | monitored-hostname quota hit for the org's plan (Phase 2) |
| `PLAN_REQUIRED` | 402 | action needs a plan the org doesn't have (Phase 2) |
| `DUPLICATE_HOSTNAME` | 409 | hostname already monitored in this org (Phase 2) |
| `NOT_FOUND` | 404 | generic entity-not-found for anything other than a scan (Phase 2). CONTRACT GAP — see amendment 2.1: §7.6's "cross-org id returns 404" rule needs a code that isn't `SCAN_NOT_FOUND`; used from Step 2 onward (org members, later monitors) |
| `WEBHOOK_INVALID_SIGNATURE` | 400 | `POST /billing/webhooks/{razorpay,stripe}` (§7.11) rejects a payload whose signature doesn't verify against the configured webhook secret. CONTRACT GAP — see amendment 2.5: not named by the phase prompt's §1.5 error list, needed because "reject unverified with 400" (§Step 6) has nowhere else to hang a machine-readable code |

A hostname that simply doesn't resolve is **not** an HTTP error. It is a `Scan` with `status: "failed"` and `error.code: "SCAN_FAILED"`, so the user still gets a shareable page.

`request_id` is generated per request, returned in the `X-Request-ID` header on every response, and included in every log line for that request.

### 7.5 `POST /api/v1/waitlist` and `GET /api/v1/admin/stats` (Gate B)

Request:
```json
{ "scan_id": "8f1c...", "email": "you@company.com" }
```
`email` is validated against a simple `local@domain.tld` shape — not full RFC 5322, deliberately, matching the scanner's own error-message register (state the problem, no over-engineering). `hostname` is never taken from the request body: it is looked up from `scan_id` server-side, so a signup can never be attributed to a hostname the visitor didn't actually scan.

Response `200`:
```json
{ "hostname": "example.com", "message": "We'll email you 30 days before example.com expires." }
```
`scan_id` referring to no known scan → `404 SCAN_NOT_FOUND`, same as `GET /api/v1/scans/{scan_id}`.

`GET /api/v1/admin/stats?token=<ADMIN_TOKEN>` returns a `text/plain` table: `daily_stats` for the last 30 days, then the last 100 scanned hostnames (`created_at`, `status`, `overall_grade`, `hostname`). Missing or mismatched `token` → `403`, plain text `Forbidden`, compared with `secrets.compare_digest`. Not part of the JSON API surface and not called by the frontend — it is a page a human opens directly.

### 7.6 Auth scheme (Phase 2)

Email OTP only. No passwords, no OAuth — nothing to hash, nothing to breach, no password-reset flow to build.

- Session token in a cookie: `httpOnly`, `Secure`, `SameSite=Lax`. Never in `localStorage`/`sessionStorage` — already forbidden by this contract's stack rules, and this is why. Cookie name `sd_session` — not specified by the phase prompt, signed off by the human 2026-08-14 (see §14 v2.1). Signed with `SESSION_SECRET` (§4).
- Lifetime: 30 days, sliding renewal on activity (each authenticated request that succeeds extends it, rather than a fixed absolute expiry).
- Every authenticated endpoint resolves `current_user` and `current_org` via a single FastAPI dependency. No endpoint reads an `org_id` out of the request body to decide authorisation — the session is the only source of "which org."
- OTP rules (all mandatory): 6 digits generated via `secrets`, stored only as a hash (never the plaintext code); 10-minute expiry; single use, invalidated immediately on a successful verify; max 5 verify attempts per code, then the code is burned regardless of whether the 6th attempt would have been correct; rate limit 3 requests per email per hour and 10 per IP per hour; code comparison is constant-time.
- `POST /api/v1/auth/otp/request` always returns `202` with an identical body whether or not the account exists — an OTP flow that answers differently for a known vs. unknown email is a user-enumeration leak, same class of problem as the existing rule against leaking org/monitor existence in §Step 2/§Step 3's cross-org tests.
- Roles (`UserRole`, §5) are enforced in a dependency, not scattered through handlers: `owner` — everything, including billing and deleting the org; `admin` — hostnames, alerts, members, no billing; `member` — read-only. A cross-org resource id returns `404`, never `403` — a member of org A must not learn that a given id belongs to org B.

### 7.7 Auth & organisation endpoints (Phase 2 Step 2)

Concrete request/response shapes for the endpoints §Step 2 names — §7.6 defined the scheme, this defines the wire format, the same relationship §7.5 has to Gate B's endpoints.

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/api/v1/auth/otp/request` | request a sign-in code | 202 |
| POST | `/api/v1/auth/otp/verify` | verify a code, start a session | 200 |
| POST | `/api/v1/auth/logout` | end the current session | 200 |
| GET | `/api/v1/auth/me` | the signed-in user | 200 |
| GET | `/api/v1/orgs/current` | the caller's current org | 200 |
| PATCH | `/api/v1/orgs/current` | rename it | 200 |
| GET | `/api/v1/orgs/current/members` | list members, paginated | 200 |
| POST | `/api/v1/orgs/current/members` | invite (or re-invite with a new role) | 201, or 200 if already a member |
| DELETE | `/api/v1/orgs/current/members/{user_id}` | remove a member | 204 |

```json
POST /api/v1/auth/otp/request
{ "email": "founder@example.com" }
-> 202 { "message": "If that email has an account, we've sent a code." }

POST /api/v1/auth/otp/verify
{ "email": "founder@example.com", "code": "123456" }
-> 200 User (§6.6), Set-Cookie: sd_session=...
   400 OTP_INVALID | OTP_EXPIRED

POST /api/v1/auth/logout
-> 200 { "message": "Logged out." }

GET /api/v1/auth/me
-> 200 User | 401 UNAUTHENTICATED

PATCH /api/v1/orgs/current
{ "name": "Acme Inc" }
-> 200 Organisation (§6.7)
```

`PATCH /api/v1/orgs/current` accepts `name` and, since Step 7 (§7.12), the five alert-preference fields (`timezone`, `quiet_hours_start`, `quiet_hours_end`, `digest_mode`, `digest_hour`) — every field optional, only the ones present in the request body are applied (same `model_fields_set` convention as `PATCH /monitors/{monitor_id}`, §7.8), so `/app/alerts`'s settings form has somewhere to write. `country`/`currency` are still excluded — "changeable only before the first subscription" (§Step 6) needs its own lifecycle rule and doesn't belong behind a plain field-level PATCH.

`GET /api/v1/orgs/current/members` returns `PaginatedList<MembershipWithEmail>` (§6.14) — `MembershipWithEmail` is §6.8 `Membership` plus one field, `email: string`, because a member list without it isn't usable in a UI. Not a new top-level contract shape, just the obvious minimum enrichment.

`POST /api/v1/orgs/current/members` — `{ "email": "...", "role": "member" }` → `MembershipWithEmail`. If the email is already a member, this updates their role instead of erroring (`200`, not `201`) — deliberate: no separate "change role" endpoint exists yet, and re-inviting to change a role is a reasonable idempotent action rather than a conflict. If the email has no `User` yet, one is created unverified — the invited person's first OTP login (§7.6) finds it and attaches to this org, never a second personal org.

Only `owner`/`admin` can reach the three member-management endpoints; `member` gets `403 FORBIDDEN`. Removing the last remaining `owner` from an org is refused with `403 FORBIDDEN` — an ownerless org is an unrecoverable state through any endpoint this contract defines.

### 7.8 Monitored hostname endpoints (Phase 2 Step 3)

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/api/v1/monitors` | list the org's monitors, paginated | 200 |
| POST | `/api/v1/monitors` | add one hostname to monitor | 201 |
| GET | `/api/v1/monitors/{monitor_id}` | fetch one | 200 |
| PATCH | `/api/v1/monitors/{monitor_id}` | rename, annotate, pause/resume | 200 |
| DELETE | `/api/v1/monitors/{monitor_id}` | stop monitoring it | 204 |
| POST | `/api/v1/monitors/bulk` | add up to 100 at once | 200 |
| POST | `/api/v1/monitors/{monitor_id}/scan` | trigger an immediate re-scan | 202 |

`POST /api/v1/monitors` and `POST /api/v1/monitors/bulk` reuse §7.2 hostname normalisation and §10's safety guard exactly as `POST /api/v1/scans` does — no parallel validation path. A hostname that doesn't currently resolve is still accepted (the monitor starts `active` and a later scan attempt reports it, the same "not an HTTP error" treatment §7.4 gives public scans); a `BLOCKED_TARGET` address is rejected synchronously, same as `POST /api/v1/scans`.

```json
POST /api/v1/monitors
{ "hostname": "example.com", "port": 443, "label": "Production", "notes": null }
-> 201 MonitoredHostname (§6.9)
   400 INVALID_HOSTNAME | BLOCKED_TARGET
   402 QUOTA_EXCEEDED
   409 DUPLICATE_HOSTNAME

GET /api/v1/monitors?state=active&page=1&per_page=25
-> 200 PaginatedList<MonitoredHostname>

PATCH /api/v1/monitors/{monitor_id}
{ "label": "Renamed", "state": "paused" }
-> 200 MonitoredHostname | 404 NOT_FOUND

POST /api/v1/monitors/bulk
{ "hostnames": ["a.example.com", "b.example.com:8443", "not a host"] }
-> 200
{
  "results": [
    { "hostname": "a.example.com", "accepted": true, "monitor": { /* MonitoredHostname */ }, "reason_code": null, "reason": null },
    { "hostname": "b.example.com:8443", "accepted": true, "monitor": { /* MonitoredHostname */ }, "reason_code": null, "reason": null },
    { "hostname": "not a host", "accepted": false, "monitor": null, "reason_code": "INVALID_HOSTNAME", "reason": "'not a host' is not a valid hostname." }
  ],
  "accepted_count": 2,
  "rejected_count": 1
}
   422 VALIDATION_ERROR — empty list, or more than 100 hostnames

POST /api/v1/monitors/{monitor_id}/scan
-> 202 ScanCreateResponse (§7.1) — cached is always false, a manual re-scan bypasses the scan cache by design
   404 NOT_FOUND
   429 RATE_LIMITED { "retry_after_seconds": 480 }
```

Rules:
- `GET /api/v1/monitors` is filterable by `state` (`?state=active`, one `MonitorState` value) and always ordered by `days_until_expiry` ascending with nulls last — the one sortable field the phase prompt names, and Step 7's dashboard confirms it as the default ("soonest expiry first. That column is the product."), so there is no `sort`/`order` query param to choose a different one.
- `DUPLICATE_HOSTNAME` is scoped to `(hostname, port)` together within an org — not specified by the phase prompt, but `example.com:443` and `example.com:8443` are different monitoring targets, matching how §10's own port allowlist already treats them as distinct scan targets.
- `QUOTA_EXCEEDED`'s `details` (deferred by v2.0's amendment note, closed here): `{ "current": 3, "limit": 3, "plan_code": "free", "upgrade_to": "watch" }` — `current`/`limit` count monitors in `active`/`paused`/`verification_pending` state (a `quota_blocked` monitor is already excluded from the count it's blocked by, so it can't double-count against itself); `upgrade_to` is the next purchasable plan from `app/plans.py`, or `null` from `watch_pro` (no further purchasable plan exists in Phase 2). `POST /api/v1/monitors/bulk` applies this per row, in order — once a batch exhausts the remaining quota, later rows in the same request are rejected with `QUOTA_EXCEEDED` too, not silently accepted over the limit.
- `POST /api/v1/monitors/{monitor_id}/scan` extends `RATE_LIMITED` (§7.4) with a third scope beyond per-IP/per-hostname: one manual re-scan per monitor per 10 minutes.
- `PATCH` accepts `label`, `notes`, and `state` — only the keys present in the request body are changed (a field simply omitted is left as-is; sent explicitly as `null` clears `label`/`notes`). `state` only accepts `"active"`/`"paused"` through this endpoint: `quota_blocked` and `verification_pending` are system-managed, not user-settable.
- Every endpoint here is scoped to `current_org` (§7.6) and requires `owner` or `admin`; `member` reaches only the `GET`s (list, single, and §7.9's `history`) — `403 FORBIDDEN` on any write. A `monitor_id` belonging to a different org is `404 NOT_FOUND`, never `403`, matching the cross-org rule established in §7.6/§7.7.

### 7.9 Scheduler and monitor history (Phase 2 Step 4)

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/api/v1/monitors/{monitor_id}/history` | grade/score timeline, one row per scan | 200 |

```json
GET /api/v1/monitors/{monitor_id}/history?page=1&per_page=25
-> 200 PaginatedList<MonitorHistoryEntry>
{
  "items": [
    { "scan_id": "8f1c...", "status": "completed", "grade": "A", "score": 94, "scanned_at": "2026-08-09T10:14:03Z" }
  ],
  "page": 1, "per_page": 25, "total": 12, "has_more": false
}
   404 NOT_FOUND
```

`MonitorHistoryEntry` is not a §6 top-level shape — a thin projection of `scans` rows already tied to this monitor (`scans.monitor_id`, internal, not part of the JSON `Scan` shape), newest first. Same role/cross-org rules as §7.8: any role can read it, a cross-org `monitor_id` is `404`.

The scheduler itself (an arq cron job, every 5 minutes) has no HTTP surface — it claims due `active` monitors with `SELECT ... FOR UPDATE SKIP LOCKED`, reserves each one's `next_scan_at` immediately (jittered ±10% around the org's plan `scan_interval_hours`, `app/plans.py`) so a slow scan is never claimed twice, and enqueues a scan through the identical `run_scan_job` path a public or manual scan uses. A scheduler-enqueued scan is capped at `SCHEDULER_MAX_CONCURRENT_SCANS` (§4, default 3) concurrently in flight via a Redis semaphore — well under the worker's `max_jobs` of 10 — so a scheduled backlog structurally cannot starve interactive public or manual scans; they share no budget with it at all.

A failed scan tied to a monitor (scheduled or manual) retries at 5 minutes, 30 minutes, then 2 hours (fixed by the phase prompt, not configurable) — the scheduler's own polling cadence is the retry mechanism, `next_scan_at` is simply set to the backoff time. After the third consecutive failure, retries stop and a `scan_failure` `AlertEvent` (§6.11) is recorded with `state: "pending"` — a durable "this needs to notify someone" record Step 5's alert engine (§7.10) picks up and delivers, same as every other `AlertType`.

### 7.10 Alert engine (Phase 2 Step 5)

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/api/v1/alerts/unsubscribe/{recipient_id}` | stop alerts to one recipient | 200 |

```json
GET /api/v1/alerts/unsubscribe/{recipient_id}
-> 200 { "message": "You will no longer receive alert emails at this address." }
   404 NOT_FOUND
```

Deliberately a `GET`, the one other exception (besides §7.5's `admin/stats`) to "every endpoint requires the session cookie where auth applies": this is the link an alert email's "Unsubscribe" line points at, so it must work from a plain click with no session and no JS.

No other endpoint exists for this step — recipient management (`AlertRecipient`, §6.10) and reading alert history are Step 7's `/app/alerts` settings page. Everything else below is engine *behaviour*, not HTTP surface.

**Triggers** — evaluated once per completed monitor-linked scan (`scanner/orchestrator.py`, before that scan's grade/certificate state overwrites the monitor's previous values):
- `cert_expiry` at each of the org's plan's `alert_lead_days` (`app/plans.py` — `60/30/14/7/3/1` paid, `14/3` free)
- `domain_expiry` at `45` and `14` days — fixed, not plan-dependent
- `grade_regression` when the grade drops at least one band versus the previous completed scan
- `new_critical_finding` when a `critical`/`high` finding's code appears that wasn't present in the previous completed scan (one `AlertEvent` per newly-appeared code)
- `scan_failure` — §7.9's concern, reusing this same firing/delivery path

Each is a **crossing** check (current value newly qualifies, the previous scan's didn't), not "still qualifies" — a certificate holding steady at 5 days across ten flapping re-scans crosses the `7`-day threshold once, not ten times. Renewing the certificate (or the domain, or recovering the grade) resets what "previous" means for the next comparison, so a later, genuinely new approach to the same threshold fires again — dedupe (below) is the second, independent guard against duplicates within one still-open episode.

**Deduplication.** Every fired alert's `dedupe_key` is `{monitor_id}:{type}:{threshold}` (§6.11) — `threshold` is the lead day for `cert_expiry`/`domain_expiry`, the grade landed on for `grade_regression`, the finding code for `new_critical_finding`, or the literal string `exhausted` for `scan_failure` (§7.9). Before creating a row, the engine checks for an existing one with the same key in `pending` or `sent` state and skips if found — "a key already in sent state never sends again."

**Quiet hours.** Per-org `timezone`/`quiet_hours_start`/`quiet_hours_end` (§6.7, defaults `Asia/Kolkata`/`21:00`/`08:00`). A non-urgent alert's `scheduled_for` is pushed to the window's local end time (converted back to UTC) if it would otherwise fall inside the window. `cert_expiry` at `≤3` days and `scan_failure` are **urgent**: `scheduled_for` is always `now`, ignoring quiet hours and digest mode both.

**Digest mode.** `Organisation.digest_mode`/`digest_hour` (§6.7). A non-urgent alert on a `"digest"` org is deferred again, past quiet hours, to the next local occurrence of `digest_hour`. Delivery batches every `AlertEvent` due for the same `(org, monitor)` at the same tick into one email — the mechanism is entirely `scheduled_for`: an urgent alert's `now` almost never coincides with anything else, so it ships alone; a digest org's non-urgent alerts pile up at the same future slot and all become due, and get sent, together.

**Delivery.** A second arq cron job (`deliver_alerts_tick`, same 5-minute cadence as §7.9's scheduler tick, `app/worker.py`) sends everything `pending` and due. Recipients: every `AlertRecipient` (§6.10) scoped to the org (`monitor_id: null`) or that specific monitor, minus anyone unsubscribed; falling back to every `owner`/`admin` membership's email when the org has added no recipients at all. No recipients found → the batch's events move straight to `state: "suppressed"`, not `sent`, not retried. `Retry 3x with backoff` reuses the delivery cron's own cadence as the backoff (the same pattern §7.9 already established for scan retries) — a failed send leaves `state: "pending"` and increments an internal attempt counter; the 3rd failure sets `state: "failed"` and logs at `ERROR`, which Sentry (Gate C) already captures — "alert us, not the customer."

**Templates.** Plain text, sentence case, no marketing chrome. A single alert's subject is `{hostname} — {condition}`; a digest batch's subject names the count (`"3 alerts across 2 hostname(s)"`) with one line per alert in the body — actionable from a phone notification without opening the mail. Every recipient resolved from a real `AlertRecipient` row gets a personalised unsubscribe link in their copy; the `owner`/`admin` membership fallback has nothing to unsubscribe from, so gets none.

### 7.11 Billing (Phase 2 Step 6)

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/api/v1/billing/plans` | pricing table, in the org's currency | 200 |
| POST | `/api/v1/billing/checkout` | start a provider checkout for a plan | 200 |
| POST | `/api/v1/billing/webhooks/razorpay` | Razorpay event delivery | 200 |
| POST | `/api/v1/billing/webhooks/stripe` | Stripe event delivery | 200 |
| GET | `/api/v1/billing/subscription` | the org's current subscription, or `null` | 200 |
| POST | `/api/v1/billing/cancel` | cancel at period end | 200 |
| GET | `/api/v1/billing/invoices` | paginated invoice history | 200 |

**Every route on this router — including the three plain `GET`s — requires `owner`.** §7.6 draws the line at billing itself, not at which HTTP verb touches it ("`admin` — hostnames, alerts, members; no billing"), so `admin` gets `403 FORBIDDEN` reading `/billing/plans` exactly as it would writing `/billing/cancel`. The two webhook routes are the deliberate exception: a payment provider sends no session cookie, so they authenticate by signature (below) instead of `current_user`/`current_org` and are reachable with no session at all.

```json
GET /api/v1/billing/plans
-> 200 { "plans": [ {
     "plan_code": "watch", "purchasable": true, "currency": "INR",
     "monthly_amount_minor": 99900, "annual_amount_minor": 839160,
     "hostname_limit": 25, "scan_interval_hours": 6,
     "alert_lead_days": [60, 30, 14, 7, 3, 1], "member_limit": 3
   }, ... ] }
```
`PricedPlan` — CONTRACT GAP, proposed: not a shape the phase prompt names, needed because "priced in the org's currency" (§Step 6) has to return something. One row per `PlanCode` (five, `§5.1`'s order), always — `secure`/`compliance` appear with `purchasable: false` and both amount fields `null` (never `0`, which would misread as "free") rather than omitted, so the pricing page can render a "contact us" row without a second endpoint. `annual_amount_minor` is `monthly_amount_minor × 12 × 0.7` (§5.1), rounded to the nearest minor unit — exact for every current plan/currency combination, never a guess.

```json
POST /api/v1/billing/checkout
{ "plan_code": "watch", "interval": "monthly", "gstin": null, "place_of_supply": null }
-> 200 { "checkout_url": "https://checkout.stripe.com/c/pay/...", "provider": "stripe", "contact_us": false }
   200 { "checkout_url": null, "provider": null, "contact_us": true }   // plan_code is secure/compliance (§5.1)
```
`gstin`/`place_of_supply` are optional India tax fields (§6.13) — CONTRACT GAP, proposed: the phase prompt says to "capture and store them now" but names no endpoint that accepts them, and checkout is the only point in this step's flow where a customer and a purchase meet, so that's where they're captured. Carried through the provider's own metadata/notes fields (never a new DB row before the provider confirms anything) and copied onto every `Invoice` created against the subscription that checkout produces. Provider is selected from `Organisation.currency` (`INR` → `razorpay`, else `stripe`, §6.7) — never a request field. **Webhooks are the source of truth for subscription state, not this response** (§Step 6, literally): this call never writes a `subscriptions` row itself, only asks the provider to start one; `GET /billing/subscription` stays `null` until a webhook confirms it.

```json
POST /api/v1/billing/webhooks/razorpay
POST /api/v1/billing/webhooks/stripe
-> 200 { "status": "ok" }
   400 WEBHOOK_INVALID_SIGNATURE
```
Signature verified against the raw request body before anything is parsed as JSON (`X-Razorpay-Signature`, HMAC-SHA256; `Stripe-Signature`, `t=…,v1=…`, both against the matching `*_WEBHOOK_SECRET`, §4) — an unverified body is never read as an event. Idempotent: the provider's own event id is recorded in an internal `billing_events` table (not part of this contract) before any `subscriptions`/`invoices`/`organisations` row is touched; a replayed delivery is recognised and no-opped at `200`, same response as the first delivery, so a provider's retry-on-non-2xx behaviour can never double-apply a plan change. Applies, per event: subscription activation (`Subscription.state → "active"`, `Organisation.plan_code` set to the purchased plan), a successful charge (one new `Invoice`, `state: "paid"`), and cancellation (`Subscription.state → "cancelled"`, `Organisation.plan_code → "free"`, excess monitors quota-blocked per §7.8's downgrade rule, never deleted).

```json
GET /api/v1/billing/subscription
-> 200 { /* Subscription, §6.12 */ }
   200 null   // no subscription has ever been confirmed for this org (still on free, or checkout never completed)
```

```json
POST /api/v1/billing/cancel
-> 200 { /* Subscription, §6.12, cancel_at_period_end now true */ }
   404 NOT_FOUND   // no active/trialing/past_due subscription to cancel
```
Sets `cancel_at_period_end` immediately but the provider keeps billing (and access keeps working) through `current_period_end` — "never immediate" (§Step 6) applies to the plan change, not to the flag. A separate arq cron tick (`app/worker.py`, 5-minute cadence, matching §7.9/§7.10) reverts `Organisation.plan_code` to `free` once `current_period_end` actually passes, applying the same downgrade quota-block. Idempotent: cancelling an already-`cancel_at_period_end` subscription returns it unchanged rather than erroring or re-calling the provider.

```json
GET /api/v1/billing/invoices?page=&per_page=
-> 200 { /* PaginatedList<Invoice>, §6.14/§6.13, newest first */ }
```

### 7.12 Alert recipients and the monitor alert log (Phase 2 Step 7)

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/api/v1/alerts/recipients` | list the org's recipients, paginated | 200 |
| POST | `/api/v1/alerts/recipients` | add one | 201, or 200 if already added |
| DELETE | `/api/v1/alerts/recipients/{recipient_id}` | remove one | 204 |
| GET | `/api/v1/monitors/{monitor_id}/alerts` | that monitor's alert history, paginated | 200 |

The two `GET`s are readable by any role, including `member` (§7.6's read-only role reads alert configuration and history same as it reads monitors); `POST`/`DELETE` require `owner`/`admin`, same `_require_manage_members`-shaped dependency as `/orgs/current/members` — recipients are explicitly `admin` territory, not billing (§7.6: "admin — hostnames, alerts, members; no billing").

```json
GET /api/v1/alerts/recipients?page=&per_page=
-> 200 { /* PaginatedList<AlertRecipient>, §6.10/§6.14 */ }

POST /api/v1/alerts/recipients
{ "email": "ops@example.com", "monitor_id": null }
-> 201 AlertRecipient (§6.10)
   200 AlertRecipient   // already exists for this (org, monitor_id, email) — idempotent, not a 409

DELETE /api/v1/alerts/recipients/{recipient_id}
-> 204 | 404 NOT_FOUND

GET /api/v1/monitors/{monitor_id}/alerts?page=&per_page=
-> 200 { /* PaginatedList<AlertEvent>, §6.11/§6.14, newest first */ }
   404 NOT_FOUND
```

Two decisions not specified by the phase prompt, made and documented rather than left implicit: `POST /alerts/recipients` is idempotent on `(org_id, monitor_id, email)` — re-adding an address already on the list returns it unchanged at `200` rather than erroring, the same convention `POST /orgs/current/members` already established for re-inviting a member, so the settings page never needs to pre-check before submitting. `verified` (§6.10) is set `true` at creation, not `false` pending a confirmation flow — no email-verification mechanism is in scope anywhere in Phase 2 (the phase prompt names none, and the alert engine, §7.10, was never gated on it — `unsubscribed` is the only flag delivery actually checks), so a `false` default would just be a permanently-wrong value with nothing to ever flip it.

`AlertEvent` (§6.11) gets its first Pydantic schema here — Steps 4/5 only ever wrote the table.

---

## 8. Finding catalogue (Phase 1, closed)

New codes require a contract amendment. `sev` is the default; modules may escalate where noted.

| Code | Module | Sev | Trigger |
|---|---|---|---|
| `CERT_EXPIRED` | certificate | critical | `not_after` in the past |
| `CERT_NOT_YET_VALID` | certificate | critical | `not_before` in the future |
| `CERT_HOSTNAME_MISMATCH` | certificate | critical | hostname not in CN or SANs |
| `CERT_SELF_SIGNED` | certificate | critical | issuer == subject |
| `CERT_EXPIRING_CRITICAL` | certificate | critical | ≤ 3 days left |
| `CERT_EXPIRING_SOON` | certificate | high | 4–14 days left |
| `CERT_EXPIRING_WARN` | certificate | medium | 15–30 days left |
| `CERT_WEAK_KEY` | certificate | high | RSA < 2048 or ECDSA < 256 |
| `CERT_WEAK_SIGNATURE` | certificate | high | SHA-1 or MD5 signature, on any certificate in the presented chain except the self-signed root (v1.4) — `evidence.position` names which one, same numbering as `chain.data.certificates` |
| `CERT_LONG_LIFETIME` | certificate | medium | `lifetime_days` > 200 |
| `CERT_NO_OCSP_STAPLING` | certificate | low | stapling absent |
| `CHAIN_INCOMPLETE` | chain | high | intermediates missing |
| `CHAIN_OUT_OF_ORDER` | chain | medium | certificates presented out of order |
| `CHAIN_UNTRUSTED_ROOT` | chain | critical | root not in trust store |
| `CHAIN_INTERMEDIATE_EXPIRING` | chain | high | intermediate expires within 30 days |
| `TLS_LEGACY_PROTOCOL` | tls | high | TLS 1.0 or 1.1 enabled |
| `TLS_NO_TLS13` | tls | low | TLS 1.3 unsupported |
| `TLS_WEAK_CIPHER` | tls | high | RC4, 3DES, NULL, EXPORT, or CBC-only suites |
| `TLS_WEAK_KEY_EXCHANGE` | tls | high | DHE parameters < 2048 bits, or ECDHE curve < 256 bits (v1.4). Only fires when `tls.data.key_exchange.bits` is actually known — see §6.4 |
| `TLS_NO_FORWARD_SECRECY` | tls | medium | no ECDHE/DHE suite negotiated |
| `DNS_NO_CAA` | dns | low | no CAA record |
| `DNS_NO_DNSSEC` | dns | info | DNSSEC not enabled |
| `DOMAIN_EXPIRING_CRITICAL` | dns | high (demoted from critical, v1.4) | domain registration ≤ 14 days, per the registry's own WHOIS record — excluded from the §9 grade-cap overrides |
| `DOMAIN_EXPIRING_SOON` | dns | high | domain registration 15–45 days, per WHOIS — excluded from the §9 grade-cap overrides (v1.4) |
| `DNS_SINGLE_NAMESERVER` | dns | medium | only one NS record |
| `SPF_MISSING` | email_auth | medium | no SPF record |
| `SPF_WEAK_POLICY` | email_auth | low | `+all` or `?all` |
| `SPF_TOO_MANY_LOOKUPS` | email_auth | medium | > 10 DNS lookups |
| `DMARC_MISSING` | email_auth | medium | no DMARC record |
| `DMARC_POLICY_NONE` | email_auth | low | `p=none` |
| `DKIM_NOT_FOUND` | email_auth | info | no selector responded |
| `HSTS_MISSING` | headers | high | no `Strict-Transport-Security` |
| `HSTS_SHORT_MAX_AGE` | headers | medium | `max-age` < 15552000 |
| `NO_HTTPS_REDIRECT` | headers | high | HTTP does not redirect to HTTPS |
| `CSP_MISSING` | headers | medium | no `Content-Security-Policy` |
| `XFO_MISSING` | headers | low | no `X-Frame-Options` and no CSP `frame-ancestors` |
| `XCTO_MISSING` | headers | low | no `X-Content-Type-Options` |
| `REFERRER_POLICY_MISSING` | headers | low | header absent |
| `PERMISSIONS_POLICY_MISSING` | headers | info | header absent |
| `SERVER_VERSION_DISCLOSED` | headers | low | `Server` header includes a version number |
| `READINESS_MANUAL_2027` | readiness | high | verdict `manual` |
| `READINESS_UNVERIFIED` | readiness | medium | verdict `semi_automated` |
| `READINESS_OK` | readiness | info | verdict `automated` |

Expiry findings are mutually exclusive — emit exactly one of the `CERT_EXPIR*` family.

Each code needs a matching `docs/findings/<code-in-hyphens>.md` file with a title, a plain-English explanation, why it matters, and how to fix it. Written for a founder, not a security engineer.

---

## 9. Grading algorithm (locked — implement exactly)

Implemented once, in `apps/api/app/grading.py`. Never duplicated in the frontend.

**Step 1 — module score.** Each module starts at 100 and subtracts per finding:

| Severity | Deduction |
|---|---|
| critical | 45 |
| high | 25 |
| medium | 10 |
| low | 4 |
| info | 0 |

Clamp to `[0, 100]`.

**Step 2 — overall score.** Weighted mean of module scores:

| Module | Weight |
|---|---|
| certificate | 30 |
| tls | 22 |
| chain | 16 |
| headers | 16 |
| email_auth | 8 |
| dns | 8 |
| readiness | 0 (informational only) |

If a module has `status == "error"` or `"skipped"`, drop it and re-normalise the remaining weights.

**Step 3 — grade bands.**

| Score | Grade |
|---|---|
| 95–100 | A+ |
| 88–94 | A |
| 78–87 | B |
| 68–77 | C |
| 55–67 | D |
| 40–54 | E |
| 0–39 | F |

**Step 4 — overrides, applied after banding.**
- Any `critical` finding anywhere caps `overall_grade` at `F`.
- Two or more `high` findings cap `overall_grade` at `C`.
- Module grades use the same bands, computed from the module score, with the same critical cap.
- **v1.4 (Gate A follow-up A4):** `DOMAIN_EXPIRING_CRITICAL` and `DOMAIN_EXPIRING_SOON` are excluded from both overrides above, at both the module and overall level — a stale or oddly-formatted WHOIS record (common on `.in`/`.co.in` and privacy-protected domains) must never be able to force a healthy TLS setup down to an `F` or a `C`. They still appear in the findings list at their own severity and still count toward their module's score in Step 1 — only the grade-cap overrides exclude them.

**Step 5 — headline.** One sentence, chosen by this precedence: highest-severity finding's `title` if severity is critical or high; otherwise `"No serious problems found — {n} smaller improvements available."`; otherwise `"Clean result. Nothing to fix."`

The grading function must be pure and unit-tested with fixed inputs. Grades cannot drift between releases without a contract amendment.

---

## 10. Safety rules (mandatory — this is a public scanner)

The scanner accepts arbitrary user input and makes network requests. It is an SSRF engine if built carelessly.

1. **Resolve first, then check.** Resolve the hostname to IPs *before* connecting, and reject if any resolved address is in: `10/8`, `172.16/12`, `192.168/16`, `127/8`, `169.254/16`, `100.64/10`, `0/8`, `::1`, `fc00::/7`, `fe80::/10`. Error: `BLOCKED_TARGET`.
2. **Pin the connection to the checked IP.** Connect to the validated address directly rather than re-resolving, to close the DNS-rebinding window.
3. **Ports.** Only `443` and `8443` are permitted in Phase 1. Anything else → `BLOCKED_TARGET`. **Exception (v1.1):** the `headers` module's plaintext HTTP→HTTPS redirect probe (§6.4 `headers.data.redirect_chain`, `http_to_https_redirect`) is additionally allowed to use port `80`, for the initial `GET http://hostname/` and for any further `http://` hops within that same probe's own redirect chain (still capped at 5 redirects, still resolve-then-validate and IP-pinned on every hop per rules 1, 2 and 4). Port `80` is not accepted anywhere else: not in `POST /api/v1/scans`, not for certificate/chain/TLS connections.
4. **Redirects.** Follow at most 5, revalidate the target of each hop against rule 1, never follow to a non-HTTP(S) scheme.
5. **Timeouts.** Per-module hard timeout of 8 s, whole-scan budget `SCAN_TIMEOUT_SECONDS`. A module that times out is `status: "error"`, never a hung request.
6. **Response size cap.** Read at most 512 KB of any HTTP body.
7. **Rate limits.** `RATE_LIMIT_PER_IP_PER_HOUR` and `RATE_LIMIT_PER_HOSTNAME_PER_HOUR`, enforced in Redis with a sliding window. Return `429 RATE_LIMITED` with `retry_after_seconds`.
8. **Blocklist.** A static denylist file for hosts we must never scan (localhost variants, cloud metadata endpoints such as `169.254.169.254`, our own infrastructure).
9. **We never send credentials, never POST to the target, never follow forms, never execute JavaScript.** Read-only, unauthenticated, GET and TLS handshakes only.
10. **User-Agent (v1.2).** The `headers` module's HTTP client identifies as a standard current desktop browser string, not the HTTP library default. Ground-truthed on swiggy.com: an unmodified `python-httpx/<version>` User-Agent gets an outright WAF block (403, no headers at all — CloudFront bot-management) on the exact same request that returns the real origin response, HSTS included, with a browser string. A blocked page is not evidence a header is missing; it is evidence the module never saw the real response. This is scoped to the `headers` module only — certificate/chain/TLS connections are raw TLS handshakes with no HTTP layer and no User-Agent to send.

Accuracy is the product. A false "expiring in 3 days" on a healthy certificate destroys trust permanently. Where a check is uncertain, return `null` and a lower-confidence finding rather than guessing.

---

## 11. Database schema (Phase 1)

```sql
scans (
  scan_id        uuid primary key,
  public_slug    varchar(12) unique not null,
  hostname       varchar(253) not null,
  port           integer not null default 443,
  status         varchar(16) not null,
  overall_grade  varchar(2),
  overall_score  integer,
  headline       text,
  result         jsonb,              -- the full Scan object from §6.1
  error_code     varchar(64),
  error_message  text,
  client_ip_hash varchar(64),        -- sha256(ip + salt), never the raw IP
  created_at     timestamptz not null default now(),
  started_at     timestamptz,
  completed_at   timestamptz,
  duration_ms    integer
)

index scans_hostname_created_idx on scans (hostname, created_at desc)
index scans_status_idx on scans (status)

waitlist_signups (            -- Gate B item 1
  id             uuid primary key,
  email          varchar(320) not null,
  hostname       varchar(253) not null,   -- from the scan record, not the request
  scan_id        uuid not null references scans(scan_id),
  client_ip_hash varchar(64),             -- sha256(ip), never the raw IP
  created_at     timestamptz not null default now()
)

index waitlist_signups_scan_id_idx on waitlist_signups (scan_id)
index waitlist_signups_created_at_idx on waitlist_signups (created_at desc)

daily_stats (                 -- Gate B item 2. One row per UTC day, upserted in place.
  day               date primary key,
  scans_started     integer not null default 0,
  scans_completed   integer not null default 0,
  scans_failed      integer not null default 0,
  share_link_opens  integer not null default 0,  -- every GET /api/v1/scans/slug/{slug}, including the submitter's own first view
  waitlist_signups  integer not null default 0
)
```

The full result lives in `result` as JSONB. Top-level columns are duplicated for querying and listing only. **Raw client IPs are never stored** — DPDP hygiene starts now, not later.

`public_slug`: 12 characters from `[A-Za-z0-9]`, generated with `secrets.choice`, retried on collision.

No personal data lives in `daily_stats` — it is five running integers per day, nothing else.

---

## 12. Design system (locked tokens)

The visual identity comes from the subject: a certificate is a *window of validity*, and the product is an instrument that reads it. The register is a clean lab instrument, not a SaaS marketing page.

**Palette**
```css
--ink:        #0B1B2B;   /* primary text, dark surfaces */
--ink-muted:  #5A6B7C;   /* secondary text */
--paper:      #F6F8FA;   /* page background */
--surface:    #FFFFFF;   /* cards */
--line:       #E3E8ED;   /* hairlines, borders */
--cobalt:     #1B4DFF;   /* accent, links, primary action */
--cobalt-soft:#E9EEFF;   /* accent backgrounds */
--pass:       #0E9F6E;
--warn:       #E4A11B;
--alert:      #D7263D;
```

**Grade colours (fixed — same everywhere)**
```
A+, A  → --pass
B, C   → --warn
D, E, F→ --alert
```

**Type**
- Display: `Space Grotesk` — headings, the grade dial, numbers. Used with restraint.
- Body: `Inter` — all prose and UI.
- Mono: `JetBrains Mono` — hostnames, serial numbers, dates, DNS records, header values. Any value that came off the wire is set in mono. This is the rule that makes the product feel like an instrument.

Scale: `12 / 14 / 16 / 20 / 26 / 34 / 48 / 64`. Body 16. Line height 1.55 for prose, 1.2 for display.

**Layout**
- Max content width `1120px`, reading column `680px`.
- Spacing scale: `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96`.
- Border radius: `6px` for controls, `10px` for cards. Nothing fully rounded except the grade dial.
- Borders are 1px `--line`. Shadows are used once, on the scan box, and nowhere else.

**Signature element — the Validity Bar.** A horizontal timeline on every result page: `not_before` on the left, `not_after` on the right, a marker for today, and a marked threshold at 15 March 2027. Set in mono, the certificate's own dates as the labels. This is the one component that gets extra design effort; everything else stays quiet.

**Voice.** Sentence case. Active voice. Errors state what happened and what to do, and never apologise. Buttons name the action and keep that name through the flow: "Scan" → "Scanning" → "Scanned". No exclamation marks. No "Oops".

**Accessibility floor, not optional.** Responsive to 360px. Visible keyboard focus rings. Colour never the sole carrier of meaning — every grade colour is paired with the letter and a text label. `prefers-reduced-motion` respected. All interactive elements reachable by keyboard.

---

## 13. Definition of done

A phase is complete only when all of these are true:

1. `docker compose up` from a clean checkout brings up postgres, redis, api, worker, and web with no manual steps beyond copying `.env.example` to `.env`.
2. `GET /api/v1/health` returns 200 with db and redis both `"ok"`.
3. Every endpoint in the phase scope returns exactly the shapes in this contract, verified by tests.
4. `pytest` passes. `ruff check` and `mypy` pass on `apps/api`. `pnpm lint` and `pnpm build` pass on `apps/web`.
5. Grading has unit tests with fixed fixtures asserting exact scores and grades.
6. Safety rules in section 10 have tests: a private IP, a blocked port, and a rate-limit trip.
7. The frontend renders correctly at 360px, 768px, and 1440px.
8. No `TODO`, no commented-out code, no unused dependencies in the shipped diff.
9. `README.md` explains setup in under ten lines.

## 14. Amendment log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-09 | Initial contract. Phase 1 scope. |
| 1.1 | 2026-08-10 | §10 rule 3: port `80` additionally permitted, scoped to the `headers` module's HTTP→HTTPS redirect probe only. Raised as a build-time contradiction between §6.4 `headers.data` and the original port allowlist; resolved by the human. |
| 1.2 | 2026-08-11 | Gate A follow-up A1. §6.4 `headers.data`: made explicit that hostname-crossing redirects are evaluated on the final hop, `final_url` names it. §10 rule 10 (new): `headers` module sends a browser User-Agent, not the HTTP library default — a WAF block is not a missing-header finding. Ground-truthed against `curl`/browser UA on google.com, flipkart.com, swiggy.com; see `docs/ACCURACY_REPORT.md` §A3b. |
| 1.3 | 2026-08-11 | Gate B: funnel capture. New §4 var `ADMIN_TOKEN`. New §7.5 endpoints `POST /api/v1/waitlist` and `GET /api/v1/admin/stats` (the latter is `text/plain`, the one documented exception to §7's "all responses `application/json`"). New §11 tables `waitlist_signups` and `daily_stats`. No auth, plans, billing, or scheduled scanning added — out of Phase 1 scope per `docs/PHASE_1_GATE.md` Gate B. |
| 1.5 | 2026-08-12 | Gate C: production deployment. New §4 vars `SENTRY_DSN` (api + worker) and `NEXT_PUBLIC_SENTRY_DSN` (web) — both empty by default, Sentry never initialised without one. No other contract-surface change (no new endpoints, fields, or finding codes); the rest of Gate C's deliverables (`docker-compose.prod.yml`, `Caddyfile`, `scripts/backup.sh`/`restore.sh`, `docs/DEPLOY.md`) are deployment infrastructure, not API contract. Two log-hygiene bugs found and fixed while verifying this live (both outside the JSON contract, noted here since they're exactly the DPDP posture CLAUDE.md rule 10 and this gate's item 8 require): uvicorn's default access log and Caddy's default JSON access log both print the raw client IP on every request regardless of what application code does — `apps/api/Dockerfile.prod` now runs with `--no-access-log`, and `deploy/caddy/Caddyfile`'s `log` block deletes `request>remote_ip`/`remote_port`/`X-Forwarded-For`. Confirmed live via `docker compose logs`. Separately, `LOG_LEVEL` (§4, present since v1.0) was a defined setting nothing ever applied — `app/logging_config.py` (new) wires it up for both the api and worker processes, and switches request logging to JSON so `request_id` (§7.4: "included in every log line for that request") actually appears, which a bare format string had been silently dropping. |
| 1.4 | 2026-08-11 | Gate A follow-ups A2 and A4 (`docs/GATE_A_FOLLOWUPS.md`), closed before Gate C. **A2:** §8 `CERT_WEAK_SIGNATURE` now scoped to every certificate in the presented chain except the self-signed root, with `evidence.position` naming which one — was leaf-only. New §8 code `TLS_WEAK_KEY_EXCHANGE` (tls, high); new §6.4 `tls.data.key_exchange` field (`type`/`bits`/`curve`, each nullable — `bits`/`curve` are null in every live scan today since pyOpenSSL exposes no negotiated-group getter, confirmed by direct introspection, not assumed; the finding only fires when `bits` is actually known, never guessed per §10). **A4:** `DOMAIN_EXPIRING_CRITICAL` demoted from critical to high — a WHOIS-derived finding must not be able to force a healthy TLS setup to `F` on its own. §9 Step 4: `DOMAIN_EXPIRING_CRITICAL`/`DOMAIN_EXPIRING_SOON` excluded from both grade-cap overrides entirely (still scored normally in Step 1, still shown at their own severity). Finding copy for both now explicitly attributes the claim to "the registry record" rather than the scanner's own voice. Test-hygiene items A3 (network-dependent tests marked and excluded from the default `pytest` run) and A5 (classifier-level unit coverage for `TLS_WEAK_CIPHER`/`TLS_WEAK_KEY_EXCHANGE`) closed alongside this amendment but don't change the contract itself. |
| 2.0 | 2026-08-14 | Phase 2 Step 1: accounts, orgs, monitoring, alerts, billing — contract surface only, no implementation yet (`docs/PHASE_2_PROMPT.md` Step 1). New §5 enums: `UserRole`, `PlanCode`, `SubscriptionState`, `BillingProvider`, `BillingInterval`, `Currency`, `AlertType`, `AlertChannel`, `AlertState`, `MonitorState`, `OtpPurpose`, and `InvoiceState` (**CONTRACT GAP** — not named by the phase prompt, proposed as `"open" \| "paid" \| "void" \| "uncollectible"`, needs explicit sign-off). New §5.1 `app/plans.py` pricing table (`free`/`watch`/`watch_pro` purchasable; `secure`/`compliance` enum-only, "contact us" at checkout). New §6.6–§6.13 data shapes: `User`, `Organisation`, `Membership`, `MonitoredHostname`, `AlertRecipient`, `AlertEvent`, `Subscription`, `Invoice`. New §6.14 paginated list envelope (`per_page` max `100` — proposed, not specified). New §4 var `SESSION_SECRET` (proposed name/mechanism — not specified). New §7.6 auth scheme: httpOnly/Secure/SameSite=Lax session cookie (`sd_session`, name proposed), 30-day sliding session, email OTP only, role enforcement via dependency, cross-org ids 404 not 403. §7.4 error table gains `UNAUTHENTICATED`, `FORBIDDEN`, `OTP_INVALID`, `OTP_EXPIRED`, `OTP_RATE_LIMITED`, `QUOTA_EXCEEDED`, `PLAN_REQUIRED`, `DUPLICATE_HOSTNAME`. Deliberately **not** in this amendment: `Organisation` alert-preference fields (timezone/quiet-hours/digest — Step 5's concern), Razorpay/Stripe env vars (Step 6's concern), the `QUOTA_EXCEEDED` error `details` payload shape (Step 3's concern) — adding them now ahead of the step that actually needs them would be exactly the "generated but not yet defined" drift rule 9 exists to prevent. |
| 2.1 | 2026-08-14 | Phase 2 Step 2 implementation: OTP auth, users/orgs/memberships, session cookie, role enforcement (`docs/PHASE_2_PROMPT.md` Step 2). Two necessary additions discovered while building it, not anticipated by v2.0, flagged rather than silently assumed: new §4 vars `RESEND_API_KEY`/`EMAIL_FROM_ADDRESS` (OTP delivery needs a real provider now, before Step 5's own `app/notify/email.py` was going to exist — that module is built early, in Step 2, for exactly this reason) and new §7.4 code `NOT_FOUND` (404) — §7.6's "cross-org id returns 404" rule had nothing to return, since `SCAN_NOT_FOUND` is scan-specific; used from the new §7.7 member endpoints onward, and will cover monitors in Step 3. New §7.7: concrete request/response shapes for every §Step 2 endpoint, `MembershipWithEmail` (§6.8 `Membership` plus `email` — a member list is unusable without it, not a new top-level shape). Member invite is idempotent (re-inviting an existing member updates their role, `200`, rather than a conflict `409` — no separate role-change endpoint exists yet). Removing an org's last `owner` is refused (`403`) rather than left possible. `PATCH /api/v1/orgs/current` scoped to `name` only — `country`/`currency` stay locked until Step 6's "changeable only before the first subscription" rule has somewhere to live. Human sign-off received on all four items v2.0 proposed pending confirmation: `InvoiceState` (`"open" \| "paid" \| "void" \| "uncollectible"`), `SESSION_SECRET` as the env var name/mechanism, `sd_session` as the cookie name, and `100` as the pagination `per_page` ceiling — none of these values changed, only their status from proposed to confirmed. |
| 2.2 | 2026-08-14 | Phase 2 Step 3 implementation: monitored hostnames (`docs/PHASE_2_PROMPT.md` Step 3). New §7.8: the seven `/api/v1/monitors...` endpoints, closing the `QUOTA_EXCEEDED` `details` shape v2.0 deliberately deferred (`{"current", "limit", "plan_code", "upgrade_to"}`, the last read from `app/plans.py`'s purchasable-plan ordering, never hardcoded). `RATE_LIMITED` (§7.4) extended, not duplicated, for the new one-manual-rescan-per-monitor-per-10-minutes limit. Two scoping decisions not specified by the phase prompt, made and documented rather than left implicit: `DUPLICATE_HOSTNAME` keys on `(hostname, port)` together, not hostname alone (port 443 and 8443 are different monitoring targets, same as §10's own allowlist treats them); quota accounting counts `active`/`paused`/`verification_pending` monitors only, so a `quota_blocked` monitor doesn't count against the very quota it's blocked by. `POST /api/v1/monitors` and `/monitors/bulk` reuse §7.2/§10 exactly as `POST /api/v1/scans` does — an unresolvable hostname is still accepted (not an HTTP error, same treatment as a public scan), a `BLOCKED_TARGET` address is rejected synchronously. Internal-only additions, not part of the JSON contract: `monitored_hostnames` table, a nullable `scans.monitor_id` FK (set when a scan is enqueued on a monitor's behalf, read back by `app/monitors.py` when that scan completes to update the monitor's denormalised `last_grade`/`last_score`/`last_scanned_at` and the certificate-expiry timestamp `days_until_expiry` is derived from). |
| 2.3 | 2026-08-14 | Phase 2 Step 4 implementation: scheduler (`docs/PHASE_2_PROMPT.md` Step 4). New §7.9: `GET /monitors/{monitor_id}/history` (`MonitorHistoryEntry`, a thin projection of `scans.monitor_id` rows — not a new §6 top-level shape) and the scheduler's own behaviour, which has no HTTP surface of its own. New §4 var `SCHEDULER_MAX_CONCURRENT_SCANS` (default `3`) — the Redis-semaphore concurrency cap `Step 4` asks for, deliberately well under `worker.py`'s `max_jobs` of `10` so scheduled scans structurally cannot starve public/manual ones (they share no budget with it at all, rather than competing for one via priority). Retry backoff (5m/30m/2h, fixed by the phase prompt) and the post-exhaustion `scan_failure` alert reuse the scheduler's own 5-minute polling cadence as the retry mechanism — no separate retry job. Internal-only additions, not part of the JSON contract: `monitored_hostnames.consecutive_failures` (drives the retry/alert threshold, reset to 0 on the next successful scan) and an `alert_events` table backing `AlertEvent` (§6.11) — Step 4 only *fires* a `scan_failure` row into it (`state: "pending"`); no Pydantic schema or endpoint exists for it yet, since nothing serialises it to JSON until Step 5's alert engine reads it, and adding one ahead of that would be exactly the "generated but not yet defined" drift rule 9 exists to prevent. `app/scheduler.py`'s scan-record creation was extracted into `app/monitors.py`'s `create_monitor_scan_record`, shared with Step 3's manual re-scan (`create_manual_rescan`) — one place a monitor-linked `scans` row is created, not two. |
| 2.4 | 2026-08-14 | Phase 2 Step 5 implementation: alert engine (`docs/PHASE_2_PROMPT.md` Step 5). New §5 enum `DigestMode` (not named by the phase prompt's enum list — `Organisation.digest_mode` needs a closed set for "immediate or daily digest"). §6.7 `Organisation` gains the five alert-preference fields v2.0's amendment note flagged as this step's own concern (`timezone`, `quiet_hours_start`, `quiet_hours_end`, `digest_mode`, `digest_hour`) — every org gets a working default the day it's created. New §7.10: the one HTTP endpoint this step adds (`GET /alerts/unsubscribe/{recipient_id}`, deliberately a bare `GET` so an email link works with no session), and the engine's behaviour — triggers, dedupe, quiet hours, digest batching, delivery/retry. `alert_recipients` table exists (backing §6.10 `AlertRecipient`) but has no management endpoint yet; falls back to org owners/admins' emails until Step 7 ships one. `AlertEvent` (§6.11) still has no Pydantic schema — Step 5 is a *writer* of that table (alongside Step 4), not a reader; nothing serialises it to JSON until Step 7's dashboard. One interpretation beyond the phase prompt's literal text, made and documented rather than left to chance: dedupe_key's `{monitor_id}:{type}:{threshold}` shape has no time or certificate-instance component, so a purely literal "sent state never sends again" would silently suppress a genuinely new alert forever after the first one — after a renewal, a domain re-registration, or a grade recovery-then-relapse. Resolved by gating alert *creation* on a crossing check (current value newly qualifies, the previous scan's didn't) rather than "still qualifies", so the dedupe guard only ever has to catch duplicates within one still-open episode, which is what "a certificate sitting at 7 days across a flapping scan must produce exactly one email" actually asks for. |
| 2.5 | 2026-08-17 | Phase 2 Step 6 implementation: billing (`docs/PHASE_2_PROMPT.md` Step 6). New §4 vars `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`/`RAZORPAY_WEBHOOK_SECRET`/`STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`, all empty by default (checkout refuses with `INTERNAL_ERROR` rather than pretending to work, same "empty = opt-in" pattern as `RESEND_API_KEY`). New §7.4 code `WEBHOOK_INVALID_SIGNATURE` (400) — CONTRACT GAP, proposed: needed for "reject unverified with 400" (§Step 6), no existing code fits. New §7.11: the seven billing endpoints, all seven owner-only including the plain `GET`s (§7.6 draws the billing line at the resource, not the verb). Two shapes not named by the phase prompt, proposed: `PricedPlan`/`BillingPlansResponse` (`GET /billing/plans`'s wire format — `secure`/`compliance` priced `null`, never `0`) and `BillingCheckoutRequest`/`BillingCheckoutResponse` (`contact_us: true` for the two non-purchasable plans, `checkout_url`/`provider` both `null` in that case). `Subscription`/`Invoice` (§6.12/§6.13) get their first Pydantic schema and `subscriptions`/`invoices` SQLAlchemy tables — the shapes themselves are unchanged from v2.0. Interpretive decisions made and documented rather than left implicit: (1) `POST /checkout` never writes a `subscriptions` row itself — only a confirming webhook does — so "webhooks are the source of truth, not the checkout redirect" holds structurally, not just as a stated intention; (2) `gstin`/`place_of_supply` (§6.13, no capture point named by the phase prompt) are captured as optional `POST /checkout` fields, carried through the provider's own metadata/notes, and copied onto every `Invoice` a confirmed subscription later produces; (3) a Razorpay checkout creates a fresh Razorpay Plan object per attempt rather than caching one, since caching would need a new persisted mapping this step has no other need for, and Razorpay itself imposes no cost or dedup requirement on duplicate Plan objects; (4) §Step 3's "excess monitors quota-blocked oldest-first by created_at" on downgrade is implemented literally — the oldest rows are the ones blocked (the newest stay active) — reusing `app.monitors.QUOTA_COUNTED_STATES`, triggered from both the cancellation webhook and a new 5-minute arq cron (`app/worker.py`) that reverts `plan_code` to `free` once a `cancel_at_period_end` subscription's `current_period_end` actually passes. Internal-only additions, not part of the JSON contract: `billing_events` table (`(provider, event_id)` unique — the idempotency ledger "store the provider event id and skip duplicates" asks for, checked before any `subscriptions`/`invoices`/`organisations` row is touched) and `app/billing/providers.py`'s normalised `WebhookEvent`, the one shape both providers' wildly different payloads are parsed into so `app/billing/service.py` has a single code path applying state regardless of which provider sent it. |
| 2.6 | 2026-08-17 | Phase 2 Step 7 implementation: the customer dashboard (`docs/PHASE_2_PROMPT.md` Step 7). Closes three items earlier amendment notes explicitly deferred to this step (v2.0/v2.4's own text, not newly invented here): `PATCH /api/v1/orgs/current` gains the five alert-preference fields (`timezone`/`quiet_hours_start`/`quiet_hours_end`/`digest_mode`/`digest_hour`), all optional and only-if-present, for `/app/alerts`'s settings form; new §7.12 `GET`/`POST /alerts/recipients` and `DELETE /alerts/recipients/{recipient_id}` for the same page's recipient list (idempotent on `(org_id, monitor_id, email)`, `verified: true` at creation — no verification flow exists anywhere in Phase 2 for it to gate on, and delivery, §7.10, never checks it); and `AlertEvent` (§6.11) finally gets a Pydantic schema, read back by new §7.12 `GET /monitors/{monitor_id}/alerts` for `/app/monitors/[id]`'s alert log. All four `/alerts/recipients`/`/monitors/{id}/alerts` routes readable by every role including `member`; the two writes are `owner`/`admin` only, matching §7.6's "admin — hostnames, alerts, members" line precisely (alerts are admin territory, distinct from billing's owner-only line). No other contract-surface change — `/app`'s seven pages, the empty states, and reusing Phase 1's result components are frontend work with no API shape of their own; `robots.ts`'s `/app/` disallow (Step 0.2) is reinforced with per-page `noindex` metadata, not replaced. |
