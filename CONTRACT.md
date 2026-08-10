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

# --- web ---
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
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
```

`overall_grade` and every module `grade` use the `Grade` set. Grade colours are fixed in section 12.

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
  "supports_renegotiation": false
}
```

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

A hostname that simply doesn't resolve is **not** an HTTP error. It is a `Scan` with `status: "failed"` and `error.code: "SCAN_FAILED"`, so the user still gets a shareable page.

`request_id` is generated per request, returned in the `X-Request-ID` header on every response, and included in every log line for that request.

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
| `CERT_WEAK_SIGNATURE` | certificate | high | SHA-1 or MD5 signature |
| `CERT_LONG_LIFETIME` | certificate | medium | `lifetime_days` > 200 |
| `CERT_NO_OCSP_STAPLING` | certificate | low | stapling absent |
| `CHAIN_INCOMPLETE` | chain | high | intermediates missing |
| `CHAIN_OUT_OF_ORDER` | chain | medium | certificates presented out of order |
| `CHAIN_UNTRUSTED_ROOT` | chain | critical | root not in trust store |
| `CHAIN_INTERMEDIATE_EXPIRING` | chain | high | intermediate expires within 30 days |
| `TLS_LEGACY_PROTOCOL` | tls | high | TLS 1.0 or 1.1 enabled |
| `TLS_NO_TLS13` | tls | low | TLS 1.3 unsupported |
| `TLS_WEAK_CIPHER` | tls | high | RC4, 3DES, NULL, EXPORT, or CBC-only suites |
| `TLS_NO_FORWARD_SECRECY` | tls | medium | no ECDHE/DHE suite negotiated |
| `DNS_NO_CAA` | dns | low | no CAA record |
| `DNS_NO_DNSSEC` | dns | info | DNSSEC not enabled |
| `DOMAIN_EXPIRING_CRITICAL` | dns | critical | domain registration ≤ 14 days |
| `DOMAIN_EXPIRING_SOON` | dns | high | domain registration 15–45 days |
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

**Step 5 — headline.** One sentence, chosen by this precedence: highest-severity finding's `title` if severity is critical or high; otherwise `"No serious problems found — {n} smaller improvements available."`; otherwise `"Clean result. Nothing to fix."`

The grading function must be pure and unit-tested with fixed inputs. Grades cannot drift between releases without a contract amendment.

---

## 10. Safety rules (mandatory — this is a public scanner)

The scanner accepts arbitrary user input and makes network requests. It is an SSRF engine if built carelessly.

1. **Resolve first, then check.** Resolve the hostname to IPs *before* connecting, and reject if any resolved address is in: `10/8`, `172.16/12`, `192.168/16`, `127/8`, `169.254/16`, `100.64/10`, `0/8`, `::1`, `fc00::/7`, `fe80::/10`. Error: `BLOCKED_TARGET`.
2. **Pin the connection to the checked IP.** Connect to the validated address directly rather than re-resolving, to close the DNS-rebinding window.
3. **Ports.** Only `443` and `8443` are permitted in Phase 1. Anything else → `BLOCKED_TARGET`.
4. **Redirects.** Follow at most 5, revalidate the target of each hop against rule 1, never follow to a non-HTTP(S) scheme.
5. **Timeouts.** Per-module hard timeout of 8 s, whole-scan budget `SCAN_TIMEOUT_SECONDS`. A module that times out is `status: "error"`, never a hung request.
6. **Response size cap.** Read at most 512 KB of any HTTP body.
7. **Rate limits.** `RATE_LIMIT_PER_IP_PER_HOUR` and `RATE_LIMIT_PER_HOSTNAME_PER_HOUR`, enforced in Redis with a sliding window. Return `429 RATE_LIMITED` with `retry_after_seconds`.
8. **Blocklist.** A static denylist file for hosts we must never scan (localhost variants, cloud metadata endpoints such as `169.254.169.254`, our own infrastructure).
9. **We never send credentials, never POST to the target, never follow forms, never execute JavaScript.** Read-only, unauthenticated, GET and TLS handshakes only.

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
```

The full result lives in `result` as JSONB. Top-level columns are duplicated for querying and listing only. **Raw client IPs are never stored** — DPDP hygiene starts now, not later.

`public_slug`: 12 characters from `[A-Za-z0-9]`, generated with `secrets.choice`, retried on collision.

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
