# Domain registration expires within days

DNS · High severity

## What it means

The registry record for the domain says its registration — not any certificate — expires within 14 days. This is what the registry's own WHOIS record states; it does not move this report's overall letter grade on its own (see "A note on this check" below).

## Why it matters

If a domain registration genuinely lapses, the domain stops resolving entirely: the site, every subdomain, every certificate issued for it, and every email address using it all stop working at once, with no partial failure mode. Certificates can be reissued in minutes; a lapsed domain can take days or weeks to recover, if it's recoverable at all before someone else registers it.

## How to fix it

Confirm the actual expiry directly with your registrar first — WHOIS records are sometimes stale or inconsistently formatted, especially for privacy-protected domains and many .in/.co.in registrations. If it's accurate, renew the registration today and turn on auto-renewal so this can't happen silently again. Make sure the payment method and contact email on file with the registrar are both current, since renewal failures are usually caused by one of those two things quietly going stale.

## A note on this check

This finding is derived entirely from the domain's public WHOIS record, a data source known to be inconsistent, sometimes redacted, and occasionally stale across registrars. Because a bad WHOIS read would otherwise be able to sink an entirely healthy site's grade, this finding is reported at its own severity but excluded from the checks that cap the overall letter grade — confirm with your registrar before treating it as certain.
