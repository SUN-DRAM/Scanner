# Certificate expires within days

Certificate · Critical severity

## What it means

This certificate has three days or fewer left before it expires.

## Why it matters

At this point there's no time left to absorb a failure. If a renewal attempt fails — an ACME rate limit, a DNS validation hiccup, a misconfigured cron job — there usually isn't enough runway left to retry before the certificate actually expires and the site starts refusing connections.

## How to fix it

Renew today, not this week. If renewal is supposed to be automated, check now whether it actually ran — a warning this close to expiry almost always means the automation already failed once and nobody noticed. Once renewed, add expiry alerts at 30, 14 and 7 days so this doesn't happen silently again.
