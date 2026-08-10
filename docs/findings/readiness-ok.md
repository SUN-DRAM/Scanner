# Certificate renewal looks automated

Readiness · Info severity

## What it means

This certificate has a short lifetime (100 days or under) from a certificate authority this scan recognizes as an automated ACME provider — the pattern consistent with a properly automated renewal setup, such as Certbot, acme.sh, or a platform's built-in ACME support.

## Why it matters

This hostname is already on the kind of short, automated renewal cadence the CA/Browser Forum's upcoming changes are pushing everyone toward — 100-day maximum lifetimes from 15 March 2027, 47-day from 15 March 2029. Nothing about that timeline should require any change here.

## How to fix it

No action needed. The one thing worth doing is making sure the renewal automation itself is monitored — a silent failure in an ACME client or cron job is the most common way a well-automated setup like this one still ends up with an expired certificate, simply because nobody notices the automation stopped working until the certificate is already gone.
