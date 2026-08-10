# No DKIM selector responded

Email authentication · Info severity

## What it means

None of the common DKIM selector names checked for this domain (`default`, `google`, `selector1`, `selector2`, `k1`, `mail`) returned a public key.

## Why it matters

This is a best-effort check, not a definitive one — DKIM selector names aren't published anywhere discoverable, so a real, correctly configured DKIM setup using an uncommon selector name would show up as "not found" here even though it's working fine. Treat this as a prompt to confirm DKIM directly with the email provider, not as proof it's missing.

## How to fix it

Check with the email service actually used to send mail for this domain (Google Workspace, Microsoft 365, a transactional email provider) to confirm DKIM signing is enabled, and note the selector name it uses so it can be verified directly with `dig txt <selector>._domainkey.<hostname>`.
