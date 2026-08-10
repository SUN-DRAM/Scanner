# An intermediate certificate is expiring

Chain · High severity

## What it means

One of the intermediate certificates in the chain — not the leaf certificate itself — expires within 30 days.

## Why it matters

It's easy to track the expiry of the main certificate and forget the intermediates entirely, since they're rarely front of mind. But the chain is only as strong as its weakest link: when an intermediate expires, the whole chain breaks, even if the leaf certificate serving the actual site is still perfectly valid.

## How to fix it

Contact the certificate authority for an updated intermediate bundle, or simply reissue the leaf certificate — reissuing typically bundles a current intermediate automatically. Either way, don't wait for the expiry date; treat it the same as any other certificate expiry warning.
