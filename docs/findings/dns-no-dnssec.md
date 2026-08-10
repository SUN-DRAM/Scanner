# DNSSEC isn't enabled

DNS · Info severity

## What it means

This domain's DNS records aren't cryptographically signed with DNSSEC.

## Why it matters

Without DNSSEC, a network attacker in a position to intercept or spoof DNS traffic — for example on a compromised network or via cache poisoning — can forge DNS responses for this domain without any way for a resolver to detect the forgery. This is a lower-urgency finding than most: DNSSEC adoption is still uneven and plenty of well-run domains don't have it, but it's a real gap where one exists.

## How to fix it

Enable DNSSEC signing with your DNS provider. Most managed DNS providers (Cloudflare, Route 53, Google Cloud DNS and others) support turning it on directly from their dashboard, and then require adding a DS record at the domain registrar to complete the chain of trust.
