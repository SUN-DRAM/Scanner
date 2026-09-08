Admin Dashboard Prompt — customer visibility for outreach

Paste into a fresh Claude Code session in D:\Scanner. CLAUDE.md and CONTRACT.md are auto-loaded. Contract v2.7 remains binding.

We're starting cold outreach and I have no way to see what's happening inside the product. /admin/stats from Gate B gives aggregate counters; I need per-account visibility so I can tell a healthy signup from a dead one and intervene while it still matters.

Extend the existing admin surface. Read-only, single-operator, behind the existing ADMIN_TOKEN. This is an internal tool — no new auth system, no roles, no multi-admin. Keep it plain.

Hard rules
Read-only. Nothing here mutates customer data. No impersonation, no session borrowing, no "log in as user." If I need to change something for a customer, I do it in psql deliberately, not through a UI that makes it easy to do by accident.
/admin/* stays out of search — robots.ts disallow plus noindex, same as /app/*.
No raw client IPs anywhere in this UI. They aren't stored and must not start being stored for this.
Every number comes from a query, never an estimate. If a figure can't be computed reliably, show "unknown" rather than a guess. Same rule the scanner runs under.
Pages
/admin/accounts

The main working view. One row per organisation:

Column	Notes
Org name / primary email	—
Signed up	Relative — "3 days ago"
Plan	Free / Watch / Watch Pro
Hostnames	Count, and the plan's limit
Last login	The signal that matters most
Last scan	—
Worst grade across their hostnames	—
Soonest expiry across their hostnames	The hook for a check-in email
Alerts sent / opened-unknown	Count of alert_events in sent
Health	Derived — see below

Sortable and filterable by plan, health, and signup date. Default sort: newest signups first.

Health, computed server-side from explicit rules — state them in the code as named constants:

activated — has ≥1 hostname and has logged in since signup
stalled — signed up, zero hostnames added
at_risk — has hostnames but no login in 14+ days
dormant — no login in 30+ days
paying — active subscription, shown regardless of the above

Activation is the metric that predicts everything else. A signup with no hostname added is a lost customer who hasn't left yet, and that's the list I want to work from.

/admin/accounts/[org_id]

One organisation in full: members and roles, every monitored hostname with its current grade and expiry, scan history, every alert event with type, state and timestamp, subscription and invoices, and the org's alert preferences.

Include an alert delivery panel. For each alert: type, state (pending/sent/failed/suppressed), recipient, timestamp. Any failed alert is an incident — the customer thinks they're covered and isn't. Surface failures prominently at the top of the page, not buried in a list.

/admin/funnel

The Phase 1 acquisition path, since that's what outreach feeds:

Scans run per day, split anonymous vs logged-in
Unique hostnames scanned per day
Waitlist signups per day
Scan → waitlist conversion rate
Waitlist → account conversion rate
Account → first hostname added (activation rate)
Account → paid conversion rate

Show a 30-day sparkline for each. Contract §13's success metrics are unmeasurable without these, and I'm about to start driving traffic that I need to be able to read.

/admin/health

Operational, so I find out before a customer does:

Scans by status in the last 24h — completed, failed, and anything stuck in queued/running beyond the timeout
Scheduler: monitors due, monitors overdue, last successful run
Alert queue: pending, failed in the last 24h
Worker memory and queue depth
Redis and Postgres connectivity

A stuck scheduler is the worst silent failure this product has. Customers hear nothing and assume everything's fine, which is precisely the outcome we sell against. Put "monitors overdue by more than an hour" at the top in red, and make it obvious at a glance.

/admin/prospects

For outreach. I'll be bulk-scanning agency client portfolios before contacting them and I need those results grouped and retrievable.

Paste a label plus a list of hostnames, scan them as a batch, store under that label
List view: label, hostname count, worst grade, count expiring within 60 days, count on certificates over 200 days
Detail view: every hostname with grade, days to expiry, certificate lifetime, and the shareable scan link
Export as CSV so I can paste findings straight into an email

Reuse the existing bulk-scan path from Step 3. These scans are not monitored hostnames — they don't belong to any org, they don't schedule, and they don't alert. Store them separately and make that separation clear in the schema, so a prospect scan can never leak into a customer's dashboard.

Also add: a daily internal digest

One email to me each morning: new signups, activations, hostnames added, alerts sent, alerts failed, scans stuck, monitors overdue, and any new paid conversion. Reuse the Phase 2 email sender.

If something breaks at 3am, I want to know at 8am, not when a customer tells me.

Contract

Add prospect_scans (or your preferred name) to §11, and the admin endpoints to §7 marked clearly as internal. Bump §14 to v2.8. Show me the diff before writing code.

Start with /admin/accounts and /admin/health — those two are what I need on day one of outreach. The rest can follow.

Design UI/UX - Clean Black and White professional format