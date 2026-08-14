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
SESSION_SECRET=                     # Phase 2 §7.6: signs the session cookie. Not named by the phase prompt — proposed here, flag if a different name/mechanism is wanted.

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
InvoiceState      = "open" | "paid" | "void" | "uncollectible"   // CONTRACT GAP: not specified by the phase prompt's §1.1 enum list — Invoice (§6.9) needs a closed state set and this is a reasonable default (mirrors Stripe's own), but it needs the human's sign-off, not an assumption baked in silently.
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
  "created_at": "2026-08-09T10:14:03Z"
}
```

Created automatically as a personal org on first OTP login (§7.6). Per-org alert preferences (timezone, quiet-hours window, digest mode) are **not** in this shape yet — Step 5 will need a small follow-up amendment to add them when the alert engine is built; not invented here ahead of that need.

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
  "state": "paid",           // InvoiceState — CONTRACT GAP, see §5's InvoiceState note
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

`page` defaults to `1`, `per_page` defaults to `25`. Maximum `per_page` is `100` — not specified by the phase prompt, proposed here as a sensible ceiling, flag if a different cap is wanted.

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
| `RATE_LIMITED` | 429 | per-IP or per-hostname limit hit |
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

- Session token in a cookie: `httpOnly`, `Secure`, `SameSite=Lax`. Never in `localStorage`/`sessionStorage` — already forbidden by this contract's stack rules, and this is why. Cookie name `sd_session` — not specified by the phase prompt, proposed here, flag if a different name is wanted. Signed with `SESSION_SECRET` (§4).
- Lifetime: 30 days, sliding renewal on activity (each authenticated request that succeeds extends it, rather than a fixed absolute expiry).
- Every authenticated endpoint resolves `current_user` and `current_org` via a single FastAPI dependency. No endpoint reads an `org_id` out of the request body to decide authorisation — the session is the only source of "which org."
- OTP rules (all mandatory): 6 digits generated via `secrets`, stored only as a hash (never the plaintext code); 10-minute expiry; single use, invalidated immediately on a successful verify; max 5 verify attempts per code, then the code is burned regardless of whether the 6th attempt would have been correct; rate limit 3 requests per email per hour and 10 per IP per hour; code comparison is constant-time.
- `POST /api/v1/auth/otp/request` always returns `202` with an identical body whether or not the account exists — an OTP flow that answers differently for a known vs. unknown email is a user-enumeration leak, same class of problem as the existing rule against leaking org/monitor existence in §Step 2/§Step 3's cross-org tests.
- Roles (`UserRole`, §5) are enforced in a dependency, not scattered through handlers: `owner` — everything, including billing and deleting the org; `admin` — hostnames, alerts, members, no billing; `member` — read-only. A cross-org resource id returns `404`, never `403` — a member of org A must not learn that a given id belongs to org B.

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
