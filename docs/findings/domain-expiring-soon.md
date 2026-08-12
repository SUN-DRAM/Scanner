# Domain registration expires soon

DNS · High severity

## What it means

The registry record for the domain says its registration expires between 15 and 45 days from now. This is what the registry's own WHOIS record states; it does not move this report's overall letter grade on its own (see "A note on this check" below).

## Why it matters

If a domain registration genuinely lapses, it takes down the site, every subdomain, every certificate, and every email address tied to it — all at once, with no partial failure. Certificate expiry is recoverable in minutes; a lapsed domain is not. This finding exists to catch it well before it becomes urgent.

## How to fix it

Confirm the actual expiry directly with your registrar first — WHOIS records are sometimes stale or inconsistently formatted. If it's accurate, renew the domain registration and turn on auto-renewal so it doesn't need tracking manually going forward. Confirm the payment method and contact email on file are current — renewal failures are almost always caused by one of those two quietly going stale, not by anyone deciding not to renew.

## A note on this check

This finding is derived entirely from the domain's public WHOIS record, a data source known to be inconsistent, sometimes redacted, and occasionally stale across registrars. It's reported at its own severity but excluded from the checks that cap the overall letter grade — confirm with your registrar before treating it as certain.
