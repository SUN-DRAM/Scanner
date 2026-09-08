# Phase 2 Gate — make it real before Phase 3

Phase 2 is code-complete and well-built. It is not yet a product: no email sends, no user can log in, no payment has been taken, and the acceptance checklist has never been run as one continuous scenario.

Four gates. Two to three days. Then Phase 3.

---

# Gate D — Email (blocking everything)

**This has been deferred five times and it now blocks the entire phase.** Without a sending provider, `ConsoleEmailSender` means OTP codes never leave the server — nobody can log in, so nothing else in Phase 2 is reachable.

## Yours, today

1. Sign up at Resend, add `sundram.tech`, take the SPF and DKIM records it generates.
2. Paste those into Spaceship, plus:
   ```
   TXT   _dmarc.sundram.tech   v=DMARC1; p=none; rua=mailto:dmarc@sundram.tech
   ```
3. Add the CAA record **only after** confirming Caddy's pinned issuer from Step 0's close-out commit. If it's pinned to Let's Encrypt, `0 issue "letsencrypt.org"` is safe. If it can still fall back to ZeroSSL, authorise both — a CAA record that locks out your own renewal path is the worst possible outage for this company specifically.
4. Set `RESEND_API_KEY` and `EMAIL_FROM_ADDRESS` on the server directly. Never on your laptop, never in the repo.

## Then, in Claude Code

Implement `ResendEmailSender` behind the existing `app/notify/email.py` interface. Then verify delivery properly, because a transactional email that lands in spam is the same as one that was never sent — and this product's entire value is an alert arriving:

- Send an OTP to a Gmail address, an Outlook address, and a corporate Google Workspace address. **All three must land in the inbox, not Promotions, not spam.**
- Run the self-scan again and confirm the email-auth module returns clean.
- Check the message headers show SPF pass, DKIM pass, DMARC pass.
- Confirm the alert email is legible on a phone and the subject line is actionable from a lock-screen notification without opening it.
- Verify the unsubscribe link works and suppresses future sends to that recipient.

---

# Gate E — Deploy and walk through it as a human

The dashboard has never been clicked by a person. `pnpm build` succeeding on 63 routes proves they compile, not that they work.

1. Deploy Phase 2 with `scripts/deploy.sh`. Confirm migrations applied and the health check passes.
2. Then **you**, in a real browser on a real phone, as a stranger who has never seen this product:
   - Sign up from scratch with an email you actually control
   - Add a hostname, watch the scan run, see the result
   - Set an alert recipient, set quiet hours, save
   - Hit the free-tier quota at 3 of 3 and see what the upgrade prompt says
   - Try to break it: back button mid-flow, refresh during a scan, an expired OTP, a wrong code five times, an empty dashboard, a very long hostname

Write down every moment you hesitate. Those are the moments a prospect leaves. Fix the top three.

Also close the two items the last session couldn't reach: verify the security group rules match `DEPLOY.md` (specifically that 5432 and 6379 are not exposed to the world), and confirm the EBS snapshot schedule exists.

---

# Gate F — Run the acceptance checklist end to end

Every item in the Phase 2 prompt's closing list, as one continuous scenario against the real deploy, not piecemeal per-step tests:

- A stranger signs up, adds a hostname, and receives a real alert email
- Dedupe verified across three consecutive scans at the same threshold — exactly one email
- Quiet hours defer a medium alert; a 3-day expiry alert is not deferred
- Downgrading a plan blocks excess monitors and deletes nothing
- Both webhooks reject an invalid signature and are idempotent on replay
- A `member` cannot reach billing; a cross-org id returns 404 on every resource type
- No secret in any log, commit, or error response
- The scheduler doesn't starve public scans; the worker stays within memory on the 4GB box

**Then force a real expiry alert.** Point a monitor at a hostname whose certificate genuinely expires within the alert window, or manipulate `next_scan_at` and the threshold on a test org, and confirm the email arrives with the right content at the right time. That is the product. It should not go live having never once fired for real.

---

# Gate G — Take one real payment

Switch Razorpay to live keys **on the server only**, then buy your own ₹999 Watch subscription with your own card.

Confirm end to end: checkout completes, the webhook fires and is verified, the subscription row is created, the plan gates lift, the quota rises to 25, the invoice generates with correct GST fields, and the money appears in your Razorpay dashboard.

Then cancel it and confirm cancellation is at period end, not immediate.

A billing integration that has never processed a live rupee is a hypothesis. This converts it to a fact for the price of one month's subscription to yourself.

Finally, run the waitlist migration against production's real `waitlist_signups` table — after a fresh database backup, and with a dry-run flag first showing exactly what it would create.

