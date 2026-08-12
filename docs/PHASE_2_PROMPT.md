Phase 2 Prompt — Production Fixes, then Accounts, Monitoring, Alerts & Billing

Paste into a fresh Claude Code session in D:\Scanner. CLAUDE.md, CONTRACT.md and ROADMAP.md are already on disk and auto-loaded — read all three in full before writing anything.

You are building Phase 2 of the SUN-DRAM Scanner. Phase 1 is live in production at sundram.tech. Everything in CONTRACT.md (currently v1.5) remains binding, and the working agreement in CLAUDE.md still applies: contract wins, complete files only, one step at a time, stop and wait after each step.

Step 0 comes first and is blocking. A few production items need closing before Phase 2 starts — two of them are costing us something every day they stay open.

Production environment (facts, not guesses)
Host: AWS EC2, Mumbai region (ap-south-1). Not DigitalOcean.
Public IPv4: 65.2.195.179 — Elastic IP, permanently allocated and associated. Survives stop/start.
Previous IP: 13.201.186.69 — released back to the AWS pool. Any surviving reference to it in code, config, docs, firewall rules or DNS is now stale and points at somebody else's machine.
Internal hostname: ip-172-31-0-62 (default VPC, 172.31.0.0/16)
OS user: ubuntu
Domain: sundram.tech, apex and www
Stack: docker compose -f docker-compose.prod.yml — caddy, web, api, worker, postgres, redis, unbound
TLS: Caddy with automatic Let's Encrypt
Step 0 — Fix production (blocking)
0.1 Sweep out the old IP address

The Elastic IP is done, which closes the biggest infrastructure risk we had. But the address changed, so anything still referencing 13.201.186.69 is now wrong and pointing at an address AWS will reassign to a stranger.

bash
grep -rn "13\.201\.186\.69" . --exclude-dir=.git --exclude-dir=node_modules
dig +short sundram.tech
dig +short www.sundram.tech

Both DNS answers must be 65.2.195.179. Then confirm from outside the box that TLS is healthy after the move:

bash
curl -sI https://sundram.tech | head -20
docker compose -f docker-compose.prod.yml logs caddy --tail=50

Caddy should already hold a valid certificate, but check the logs for failed ACME attempts during the switchover — Let's Encrypt rate limits are per-domain per-week, and a burst of failures while DNS was mid-propagation can leave us temporarily unable to re-issue.

Then update our own SSRF denylist. Contract §10 rule 8 requires the static denylist to cover our own infrastructure, and it currently can't know about the new address. Add 65.2.195.179 and the VPC range 172.31.0.0/16, and remove 13.201.186.69 — that address now belongs to someone else and blocking it would be both wrong and a small information leak about our history. Add a test asserting our own public IP is rejected with BLOCKED_TARGET.

0.2 robots.txt is refusing crawlers — URGENT

An automated fetch of https://sundram.tech was refused by robots.txt. Our entire top-of-funnel is organic search. If crawlers are blocked, the scanner acquires nobody and the compounding never starts.

Diagnose before changing anything:

bash
curl -s https://sundram.tech/robots.txt
curl -s https://sundram.tech/sitemap.xml | head -50

Read apps/web/app/robots.ts and work out whether it emits a blanket Disallow: /, a user-agent-specific rule, or something conditional. The likely cause is an environment gate — a check on APP_ENV, NODE_ENV or NEXT_PUBLIC_SITE_URL that only permits crawling when it detects production, with that variable not actually set to production in the running container. Confirm:

bash
docker compose -f docker-compose.prod.yml exec web env | grep -Ei 'APP_ENV|NODE_ENV|SITE_URL'

Required end state:

robots.txt allows all user agents everywhere except /api/, /admin/ and /app/
Sitemap: https://sundram.tech/sitemap.xml declared in it
sitemap.xml returns 200 with absolute https://sundram.tech URLs — not localhost, which is the other classic symptom of a mis-set site URL
Individual scan result pages stay out of the sitemap (ephemeral, unbounded) but must not be noindex — a shared scan link is our distribution mechanism and has to render for a crawler generating a link preview
Every page's canonical URL and OG tags use the real domain

Add a test asserting the production robots.ts output allows crawling, so this can't silently regress.

Verify from outside the server after the fix, then tell me — I'll submit the sitemap in Google Search Console.

0.3 Correct the runbook to match reality

docs/DEPLOY.md was written against a different provider than the one we deployed to. A runbook describing the wrong host is worse than no runbook at 2am. Rewrite it against AWS EC2 Mumbai using the facts above:

Security groups, not a provider firewall UI. Document the exact inbound rules: 22 restricted to my IP, 80 and 443 open, everything else closed. Check what's actually configured and flag any discrepancy — an exposed 5432 or 6379 is a live incident, not a documentation issue. Also confirm no rule still references the old IP.
Elastic IP — done and associated. Record it in the runbook as 65.2.195.179, note that it survives stop/start, and note that releasing it while detached is the one action that would break DNS again.
Backups to S3 Mumbai (ap-south-1) via an IAM role attached to the instance, not access keys on disk. Update scripts/backup.sh and scripts/restore.sh and re-run the full backup → scratch restore → row-count verification cycle.
EBS snapshots as a second layer, with the schedule documented.
Provisioning, redeploy, rollback and restore steps rewritten with real ubuntu@65.2.195.179 commands.
Record the instance type and whether swap is configured. A 4GB box running six containers plus concurrent scans will OOM-kill the worker without it.
0.4 Scan our own domain — the credibility check

Run our scanner against sundram.tech and paste the full result.

If it isn't A+, fix our site before anything else. A certificate-readiness company whose own site grades B is the most avoidable credibility failure available to us, and scanning us is the first thing a skeptical prospect does.

Getting to A+: HSTS with a long max-age and includeSubDomains, complete chain, TLS 1.3, a CSP that actually fits the app, X-Content-Type-Options, a referrer policy, and a CAA record authorising Let's Encrypt. Most of it is Caddy configuration and DNS.

Also confirm the email-auth module comes back clean once SPF, DKIM and DMARC are set up on sundram.tech. That's a prerequisite for Step 5 regardless — our alert emails are worthless if they land in spam.

Stop after Step 0 and show me everything. Phase 2 starts only once production is correct.

Phase 2 proper
What Phase 2 is

The first phase that takes money. Phase 1 tells a stranger their certificate expires in 12 days. Phase 2 remembers, watches, and tells them again before it happens — for ₹999/month.

The product ladder is "alert me" → "fix it automatically" → "prove it to my auditor." Phase 2 is the first rung, and the rung that puts a payment method on file. Every later upsell is a warm conversation because of it.

In scope: email OTP auth, organisations, monitored hostnames with quotas, scheduled re-scanning, the email alert engine, Razorpay and Stripe billing, the customer dashboard.

Out of scope, and I will reject it: the sidecar, auto-TLS, ACME, shadow mode, compliance evidence packs, agency multi-tenancy, WhatsApp alerts, PDF reports. Those are Phases 3–6.

Decisions already made — do not relitigate
Email OTP only. No passwords, no OAuth. Nothing to store, nothing to breach, lowest friction for Indian SMB, and no password-reset flow to build.
Email alerts only in Phase 2. WhatsApp is Phase 3. The reasoning is role continuity: when an engineer leaves, a phone number has to be updated by someone who remembers to; a role mailbox like ops@company.com survives the handover on its own. Design for that explicitly — see Step 5.
Razorpay for INR, Stripe for USD. Both in test mode for this entire phase.
You will never see a live API key. All secrets come from env vars. If you need a key to proceed, stop and tell me which variable to set. Never print, echo, log, or commit a key.
Step 1 — Contract amendment v2.0

Write this into CONTRACT.md before any code. Show me the diff and wait for approval.

1.1 New enums (§5 additions)
UserRole          = "owner" | "admin" | "member"
PlanCode          = "free" | "watch" | "watch_pro" | "secure" | "compliance"
SubscriptionState = "trialing" | "active" | "past_due" | "cancelled" | "expired"
BillingProvider   = "razorpay" | "stripe"
BillingInterval   = "monthly" | "annual"
Currency          = "INR" | "USD"
AlertType         = "cert_expiry" | "domain_expiry" | "grade_regression" | "scan_failure" | "new_critical_finding"
AlertChannel      = "email"
AlertState        = "pending" | "sent" | "failed" | "suppressed"
MonitorState      = "active" | "paused" | "quota_blocked" | "verification_pending"
OtpPurpose        = "login" | "email_change"

AlertChannel is a single-value enum today so Phase 3 can add whatsapp and slack without a shape change.

1.2 Plans (single source of truth, app/plans.py)
Code	INR/mo	USD/mo	Hostnames	Scan interval	Alert lead days	Members
free	0	0	3	24h	14, 3	1
watch	999	29	25	6h	60, 30, 14, 7, 3, 1	3
watch_pro	2999	79	100	6h	60, 30, 14, 7, 3, 1	10

secure and compliance exist in the enum and the pricing table but are not purchasable in Phase 2 — checkout returns a "contact us" path. Do not build their features.

Annual billing is 30% off the monthly rate × 12. Cash today is worth more than ARPA later, so surface annual prominently at checkout.

1.3 New data shapes (§6 additions)

Full Pydantic models and matching TypeScript in types/contract.ts, in the same edit, per rule 4:

User — user_id, email, email_verified, created_at, last_login_at
Organisation — org_id, name, country, currency, plan_code, created_at
Membership — org_id, user_id, role, invited_by, joined_at
MonitoredHostname — monitor_id, org_id, hostname, port, state, label, notes, last_scan_id, last_grade, last_score, last_scanned_at, next_scan_at, days_until_expiry, created_at
AlertRecipient — recipient_id, org_id, monitor_id (nullable = org-wide), email, verified, created_at
AlertEvent — alert_id, org_id, monitor_id, type, state, severity, subject, dedupe_key, scheduled_for, sent_at, recipients, payload
Subscription — subscription_id, org_id, plan_code, provider, interval, currency, state, current_period_start, current_period_end, cancel_at_period_end, provider_subscription_id
Invoice — invoice_id, org_id, number, amount_minor, currency, state, issued_at, paid_at, pdf_url, gstin, place_of_supply

Money is always an integer in minor units (amount_minor: paise or cents) with an explicit currency. Never a float. Never a formatted string from the backend.

1.4 Paginated list envelope (new, every list endpoint)
jsonc
{ "items": [], "page": 1, "per_page": 25, "total": 137, "has_more": true }
1.5 Auth scheme (§7 addition)
Session token in an httpOnly, Secure, SameSite=Lax cookie. Never in localStorage — the contract already forbids browser storage and this is why.
30-day lifetime, sliding renewal on activity.
Every authenticated endpoint resolves current_user and current_org via a FastAPI dependency. No endpoint reads an org_id from the request body to decide authorisation.
New error codes: UNAUTHENTICATED (401), FORBIDDEN (403), OTP_INVALID (400), OTP_EXPIRED (400), OTP_RATE_LIMITED (429), QUOTA_EXCEEDED (402), PLAN_REQUIRED (402), DUPLICATE_HOSTNAME (409).

Bump §14 to v2.0.

Step 2 — Auth and organisations
POST /api/v1/auth/otp/request — {email}. Always returns 202 with an identical body whether or not the account exists. Never reveal whether an email is registered.
POST /api/v1/auth/otp/verify — {email, code} → sets the session cookie, creates the user and a personal org on first login
POST /api/v1/auth/logout, GET /api/v1/auth/me
GET/PATCH /api/v1/orgs/current, GET/POST/DELETE /api/v1/orgs/current/members

OTP rules, all mandatory:

6 digits via secrets, stored only as a hash
10-minute expiry, single use, invalidated on use
Max 5 verify attempts per code, then burn it
Rate limit: 3 requests per email per hour, 10 per IP per hour
Constant-time comparison

Member invites are an email plus a role. The invited person completes the normal OTP login and is attached to the org. No separate invite-token flow.

Roles, enforced in a dependency rather than scattered through handlers:

owner — everything, including billing and deleting the org
admin — hostnames, alerts, members; no billing
member — read-only

Tests: an unverified session reaches nothing; a member gets 403 on a write; a user from org A gets 404, not 403, on org B's monitor id, so we don't leak existence.

Step 3 — Monitored hostnames
GET /api/v1/monitors — paginated, filterable by state, sortable by days_until_expiry
POST /api/v1/monitors — reuses Phase 1's §7.2 normalisation and §10 safety guard. No exceptions, no parallel code path.
GET/PATCH/DELETE /api/v1/monitors/{monitor_id}
POST /api/v1/monitors/bulk — up to 100 hostnames pasted or uploaded, per-row accepted/rejected with reasons
POST /api/v1/monitors/{monitor_id}/scan — manual re-scan, 1 per monitor per 10 minutes

Quota breaches return 402 QUOTA_EXCEEDED with {"current": 25, "limit": 25, "plan_code": "watch", "upgrade_to": "watch_pro"}. The frontend renders the upgrade prompt from that payload and never hardcodes plan limits.

On downgrade, when an org is over quota, never delete hostnames. Set the excess to quota_blocked, oldest-first by created_at, and let the user choose what to keep. Deleting customer data on a billing event is unforgivable.

Step 4 — Scheduler

An arq cron job every 5 minutes claiming due monitors and enqueuing scans.

Claim with SELECT ... FOR UPDATE SKIP LOCKED so two workers never scan the same monitor
Jitter next_scan_at by ±10% so 500 monitors from one bulk import don't stampede every six hours forever
Global concurrency cap via a Redis semaphore. A scheduled backlog must never starve interactive public scans — the public scanner takes priority, it's the acquisition channel
Failed scans retry with backoff (5m, 30m, 2h), then mark the monitor and fire a scan_failure alert
Results persist to the existing scans table with monitor_id set, so history is queryable per hostname

GET /api/v1/monitors/{monitor_id}/history returns the grade and score timeline.

Given the 4GB instance: bound worker concurrency explicitly and confirm memory headroom under a full scheduled cycle. An OOM-killed worker that silently stops scanning is the worst failure mode available to an alerting product — the customer hears nothing and assumes all is well.

Step 5 — Alert engine

This is what customers actually pay for. Too noisy and they turn it off; too quiet and they churn.

Triggers

cert_expiry at each plan lead day (60/30/14/7/3/1)
domain_expiry at 45 and 14 days
grade_regression when the grade drops a band
scan_failure after retries are exhausted
new_critical_finding when a critical or high finding appears that wasn't in the previous scan

Deduplication — non-negotiable. Every alert carries a dedupe_key of {monitor_id}:{type}:{threshold}. A key already in sent state never sends again. A certificate sitting at 7 days across a flapping scan must produce exactly one email.

Quiet hours. Per-org timezone (default Asia/Kolkata), configurable window (default 21:00–08:00). Non-critical alerts scheduled inside the window defer to the next open hour. cert_expiry at ≤3 days and scan_failure ignore quiet hours.

Digest mode. Org setting: immediate or daily digest at a chosen hour. Digest batches everything non-urgent into one email. Default: digest on free, immediate on paid.

Recipients — build for role continuity. Recipients attach to the org (all monitors) or to a single monitor. On first setup, suggest a role address (ops@, devops@, it@) with copy explaining why: a shared mailbox survives an engineer leaving, a personal one doesn't. Every alert email names the hostname, the org, and the action, so a new hire receiving one cold can act without context. Per-recipient unsubscribe link, plus a link to the live scan result.

Delivery behind an interface (app/notify/email.py) so Phase 3 can add channels. Env vars only. Retry 3× with backoff, record failures in AlertEvent.state, and alert us, not the customer, on repeated send failure.

Templates: plain, text-first, mobile-legible, sentence case, no marketing chrome. Subject format: {hostname} — certificate expires in 7 days. It must be actionable from a phone notification without opening the mail.

Tests: dedupe across repeated scans, quiet-hours deferral, critical bypass, digest batching, unsubscribe suppression.

Step 6 — Billing
Plans from app/plans.py only. Never a hardcoded price in a handler or a component.
GET /api/v1/billing/plans — priced in the org's currency
POST /api/v1/billing/checkout — {plan_code, interval} → provider checkout session
POST /api/v1/billing/webhooks/razorpay and /stripe — signature verification mandatory, reject unverified with 400
GET /api/v1/billing/subscription, POST /api/v1/billing/cancel (at period end, never immediate)
GET /api/v1/billing/invoices (paginated)

Provider selection: INR → Razorpay, USD → Stripe, from org country at signup, changeable only before the first subscription.

Webhooks are the source of truth for subscription state, not the checkout redirect. Handle them idempotently — providers retry, and double-applying a plan change is a real bug. Store the provider event id and skip duplicates.

India tax fields on invoices: optional customer GSTIN, place of supply, HSN/SAC code. Capture and store them now even if the rate logic stays simple — retrofitting means reissuing invoices.

Test mode throughout. RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET — all env, all absent from the repo, all present in .env.example with empty values.

Add docs/BILLING_TESTING.md with the exact test cards and webhook-replay commands for both providers.

The webhook endpoints must be reachable from the public internet at https://sundram.tech/api/v1/billing/webhooks/.... Confirm Caddy routes them and that no rate limit or bot rule blocks provider IPs — a silently dropped webhook means a customer pays and never gets their plan. When registering the endpoint URLs in the Razorpay and Stripe dashboards, use the domain, never the IP.

Step 7 — Dashboard

Contract §12 design tokens apply unchanged. Same instrument, logged in.

/login — one email field, then one code field. Nothing else on the page.
/app — the hostname table: hostname, grade, days until expiry, last scanned, state. Default sort: soonest expiry first. That column is the product.
/app/monitors/[id] — full latest result (reuse the Phase 1 result components), grade history sparkline, alert log
/app/monitors/new — single add and bulk paste
/app/alerts — recipients, quiet hours, digest settings
/app/billing — plan, usage against quota, upgrade, invoices
/app/team — members and roles

Reuse every Phase 1 component. If a result panel needs changing for the dashboard, change it once and use it in both places — do not fork it.

The empty state matters more than the full state: a new user with zero hostnames sees one obvious input and a line about what happens next. A free user at 3 of 3 sees the upgrade path without a modal interrupting them.

/app/* must be noindex and excluded in robots.ts — coordinate with the Step 0.2 fix so the two don't fight.

Step 8 — Migrate the waitlist, then verify

The waitlist_signups table from Gate B holds people who scanned a domain and asked to be warned before it expires. We promised them an email 30 days out. Honour it.

A one-off command that, per signup: creates the user, creates a personal org on the free plan, adds the hostname as a monitor, sets the signup email as recipient. Then one email: "You asked us to warn you before {hostname}'s certificate expires. We're now watching it. Here's your dashboard."

That is the warmest launch audience available to us — they've already seen their own bad grade.

Acceptance for Phase 2, all of CONTRACT.md §13 plus:

A stranger signs up, adds a hostname, and receives a real alert email end-to-end in test mode
Alert dedupe verified across three consecutive scans at the same threshold
Quiet hours defer a medium alert and do not defer a 3-day expiry alert
Downgrading a plan blocks excess monitors and deletes nothing
Both webhook endpoints reject an invalid signature and are idempotent on replay
A member cannot reach billing; a cross-org id returns 404
No secret appears in any log, any commit, or any error response
The scheduler does not starve public scans under load, and the worker stays within memory on the 4GB instance
Start



Step 0 only. Diagnose all four items, show me what you found before fixing anything, then fix and verify. Do not begin Step 1 until I've seen production come back clean.