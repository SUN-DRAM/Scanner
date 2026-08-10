# This certificate needs a manual renewal process

Readiness · High severity

## What it means

This certificate's lifetime is longer than 100 days, and its issuer isn't one this scan recognizes as an automated (ACME) certificate authority — the pattern consistent with a certificate that gets renewed by someone remembering to do it, rather than by a script.

## Why it matters

The CA/Browser Forum is capping maximum certificate lifetimes at 100 days from 15 March 2027, and 47 days from 15 March 2029. A manual process that works today — renew once or twice a year, mark a calendar — becomes unworkable at that cadence. Every hostname still running on manual renewal by March 2027 is a hostname at real risk of an unplanned outage the first time the renewal gets missed, which at a 100-day cycle will happen faster than most teams expect.

## How to fix it

Move to an automated ACME client — Certbot, acme.sh, or built-in support from your hosting platform or load balancer — with Let's Encrypt, ZeroSSL, Google Trust Services or Buypass, before 15 March 2027. This is the single highest-leverage fix on this report: once renewal is automated, certificate lifetime stops being something that needs tracking at all.
