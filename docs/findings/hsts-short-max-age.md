# HSTS max-age is short

Headers · Medium severity

## What it means

The site sends an HSTS header, but its `max-age` is well under the recommended 180 days (15552000 seconds) — meaning browsers stop enforcing HTTPS-only for this site sooner than they should.

## Why it matters

HSTS only protects a visitor for as long as the browser remembers to enforce it. A short `max-age` means that protection lapses quickly if the visitor doesn't return to the site often enough to refresh it, reopening the exact downgrade window HSTS exists to close.

## How to fix it

Increase the HSTS `max-age` to at least 15552000 seconds (180 days) once HTTPS is confirmed working reliably everywhere on the site, including all subdomains if `includeSubDomains` is also set.
