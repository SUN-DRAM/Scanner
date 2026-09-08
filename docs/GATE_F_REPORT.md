# Gate F report — acceptance checklist run against the real deploy

**Date:** 2026-08-24
**Scope:** `docs/PHASE_2_GATE.md` Gate F, run as one continuous scenario against `https://sundram.tech` (production, AWS EC2 `65.2.195.179`), not piecemeal per-step tests.

## Critical finding — production has no backups

Independent of the acceptance checklist itself: **`crontab -l` for the `ubuntu` user on the production instance returns "no crontab for ubuntu"**, and **the S3 bucket `sun-dram-scanner-backups` does not exist** (`NoSuchBucket`). `docs/DEPLOY.md` §3.6 describes both as already set up; neither is. This means:

- There has never been a single automated backup of the production database.
- `scripts/backup.sh` has apparently never been run, not even once by hand.
- `scripts/restore.sh` has nothing to restore from.

This is a live operational risk, not a documentation gap — a bad migration, a fat-fingered `DELETE`, or a corrupted volume right now would be unrecoverable. Recommend treating this as blocking ahead of Gate G (taking a real payment) — a paying customer's data deserves at least the S3 backup layer that DEPLOY.md already assumes exists. Fix is mechanical: create the bucket + IAM policy (DEPLOY.md §1.5), run `./scripts/backup.sh` once by hand, then add the cron line (§3.6).

EBS snapshots (the second backup layer, DEPLOY.md §3.7) could not be checked from this session — see "Not verifiable from this session" below.

## Checklist results

| Item | Result |
|---|---|
| Stranger signup → hostname → real alert email | **Pass.** Real OTP signup (`sharvesh4705+gatef@gmail.com`), OTP landed in inbox in seconds, real session issued. Added `sundram.tech` as a monitor, triggered a real scan (A+, score 98, 78 days to expiry) — golden path works end to end on the real deploy. |
| Dedupe across 3 consecutive scans at the same threshold — exactly 1 email | **Pass.** Simulated a cert crossing 3 days via the real `evaluate_and_fire_alerts` engine function against a copy of a real scan record (see Method below); 2 further "scans" holding at the same value fired zero new `AlertEvent` rows for that dedupe key. Exactly one `cert_expiry:3` event was created and exactly one email sent for it. |
| Quiet hours defer a medium alert; a 3-day expiry alert is not deferred | **Pass.** Same test org, quiet hours window set to bracket the current time. A MEDIUM-severity 30-day threshold alert (needs a paid plan's longer lead days — see Method) was deferred to the window's end and delivered then, batched with two HIGH alerts into one digest email (`"3 alerts across 1 hostname(s)"`, matching the contract's template exactly). The CRITICAL 3-day alert sent immediately, ignoring the same active quiet-hours window. |
| Downgrading a plan blocks excess monitors and deletes nothing | **Pass.** Test org had 5 monitors on `watch` (limit 25); calling the real `apply_plan_downgrade()` against `free` (limit 3) left all 5 rows in place, blocked the 2 oldest (`quota_blocked`, `next_scan_at` cleared), kept the 3 newest active — oldest-first, exactly as `billing/service.py` documents. A follow-up `POST /monitors` then correctly returned `402 QUOTA_EXCEEDED` with `{"current":3,"limit":3,"plan_code":"free","upgrade_to":"watch"}`. |
| Both webhooks reject an invalid signature and are idempotent on replay | **Partial pass — Razorpay only.** Razorpay: garbage/missing `X-Razorpay-Signature` → `400 WEBHOOK_INVALID_SIGNATURE`; a validly-signed synthetic `subscription.activated` event posted twice produced `billing_webhook_duplicate` in the logs on the second delivery, exactly one `subscriptions` row, exactly one `billing_events` ledger row. **Stripe could not be tested** — `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` are unset in production (by design, USD/Stripe isn't live yet), so the webhook returns `500 INTERNAL_ERROR` ("Stripe is not configured yet") before it ever reaches signature verification, rather than the `400` the checklist item expects. Not a bug — just untestable in the current deploy config. Re-run this half once Stripe goes live. |
| A `member` cannot reach billing; a cross-org id returns 404 on every resource type | **Pass.** A `member`-role session got `403 FORBIDDEN` on `GET /billing/plans`, `GET /billing/subscription`, and `POST /monitors` (write), while `GET /monitors` (read) succeeded. A second, unrelated org's monitor id returned `404 NOT_FOUND` (never `403`) from the first org on: `GET`, `PATCH`, `DELETE`, `/history`, `/alerts`, `/scan`, and `DELETE /orgs/current/members/{user_id}`. |
| No secret in any log, commit, or error response | **Pass.** Scanned `api`/`worker` container logs (last 30 min, covering every test in this session) and the full git history for API keys, webhook secrets, `SESSION_SECRET`, `POSTGRES_PASSWORD`, session-cookie values, and AWS-style keys — clean. Only placeholders (`CHANGE_ME_...`) and the deliberate `scratch` password for `restore.sh`'s throwaway scratch container appear in git history. Every error response returned during testing carried only its documented shape, no internals. |
| The scheduler doesn't starve public scans; the worker stays within memory on the 4GB box | **Light pass, not a full stress test.** A burst of 8 concurrent public scans landed cleanly (7×202, 1×200 cached) while a real scheduler-triggered rescan of the test monitor ran independently. `worker` stayed at 118MiB/768MiB (15%) throughout. This confirms headroom under a small burst; it is not a genuine sustained-load test of the full 4GB instance under a real scheduled-backlog-plus-public-traffic collision — flagging as a real gap if that scenario matters before Gate G. |
| **Forced real expiry alert**, correct content and timing | **Pass, by simulation rather than a naturally-expiring cert** — see Method. Email arrived with subject `"sundram.tech — certificate expires in 3 days"` and body `"The certificate for sundram.tech expires in 3 days, on 2026-08-27."`, sent immediately (07:20:00Z) despite active quiet hours, exactly matching `app/alerts.py`'s template. |

## Not verifiable from this session

- **Security group rule detail** (is `22` restricted to a specific IP, or `0.0.0.0/0`?). The instance's IAM role is deliberately scoped to only the S3 backup bucket (confirmed: `ec2:DescribeInstances` → `UnauthorizedOperation`), so it can't be used to read its own security group — correctly locked down, but it means this needs the AWS console. What *was* confirmed from outside the instance: `5432` and `6379` both time out (not reachable), `443` connects immediately.
- **EBS snapshot schedule.** Same reason — needs AWS console (EC2 → the instance's volume → Actions, or Data Lifecycle Manager), not reachable via the instance's own restricted role.

## Method note — how the alert-engine tests were run

`sundram.tech`'s real certificate has 78 days left, so nothing would cross a real alert threshold today. Per Gate F's own instructions ("manipulate `next_scan_at` and the threshold on a test org"), the dedupe/quiet-hours/forced-alert tests were run by calling `app.alerts.evaluate_and_fire_alerts()` — the real, unmodified production function — directly against a copy of a real completed scan record for the test monitor, with `days_until_expiry` patched to specific values and `MonitoredHostname.cert_not_after` set to represent each step's "previous scan" state. This exercises the actual crossing/dedupe/quiet-hours/digest logic and the actual Resend delivery path; only the certificate-expiry *input* is synthetic, not the evaluation or delivery code. The org was temporarily bumped to the `watch` plan (to unlock the 30-day MEDIUM-severity threshold; `free` only has 14/3-day leads) and later downgraded back as part of the downgrade test. All writes were scoped to `org_id = 603c503d-9f99-4a06-bf24-81f1ebdf72cc` and its own monitors — three test accounts were created this session (`sharvesh4705+gatef{,2,3}@gmail.com`, real OTP signups, real inbox), none of them touching any pre-existing production data. Every database write of this kind was proposed to and approved by the user in-session before running.

## Test artifacts left in production

Three real accounts/orgs from this session remain in the database (harmless, isolated, no other org's data touched):

- `sharvesh4705+gatef@gmail.com` — owner of `org_id 603c503d-...`, now on the `watch` plan with an active test subscription (`sub_gateF_test`, created by the webhook-replay test) and 5 monitors (2 `quota_blocked` from the downgrade test, 3 `active`). Quiet hours are still set to `12:40`–`12:52` and digest mode to `immediate` from the test.
- `sharvesh4705+gatef2@gmail.com` — a `member` of the same org (RBAC test).
- `sharvesh4705+gatef3@gmail.com` — owner of a second, unrelated personal org with one monitor (`badssl.com`), used only for the cross-org 404 test.

Left in place as an audit trail rather than deleted unilaterally — say the word if you want them cleaned up.
