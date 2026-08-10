# Domain registration expires within days

DNS · Critical severity

## What it means

The domain's registration itself — not any certificate — expires within 14 days.

## Why it matters

This is the finding that matters more than any other on this report. If a domain registration lapses, the domain stops resolving entirely: the site, every subdomain, every certificate issued for it, and every email address using it all stop working at once, with no partial failure mode. Certificates can be reissued in minutes; a lapsed domain can take days or weeks to recover, if it's recoverable at all before someone else registers it.

## How to fix it

Renew the domain registration today, directly with the registrar. Once renewed, turn on auto-renewal so this can't happen silently again — and make sure the payment method and contact email on file with the registrar are both current, since renewal failures are usually caused by one of those two things quietly going stale.
