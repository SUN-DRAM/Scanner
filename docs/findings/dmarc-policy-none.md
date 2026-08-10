# DMARC policy is monitor-only

Email authentication · Low severity

## What it means

This domain's DMARC policy is `p=none` — it requests reports on mail that fails SPF or DKIM, but doesn't instruct receiving servers to do anything about it.

## Why it matters

`p=none` is the right starting point for DMARC, not the end point. It's useful for finding out what's actually sending mail as this domain before enforcing anything, but left in place indefinitely it provides visibility without protection — spoofed email that fails SPF and DKIM still gets delivered exactly as if DMARC weren't there at all.

## How to fix it

Once the DMARC aggregate reports show that all legitimate mail sources are accounted for and passing, move the policy to `p=quarantine`, and eventually `p=reject` once confident nothing legitimate is being caught.
