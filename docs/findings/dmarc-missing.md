# No DMARC record found

Email authentication · Medium severity

## What it means

There's no DMARC record for this domain, so there's no published policy telling receiving mail servers what to do with email that fails SPF or DKIM checks — and no reporting that would reveal spoofing attempts happening against this domain.

## Why it matters

SPF and DKIM on their own only tell a receiving server whether a message passed or failed — DMARC is what turns that into an actual policy (reject it, quarantine it, or just watch) and gives the domain owner visibility into who's sending mail claiming to be from this domain, including attackers. Without it, this domain is easier to spoof convincingly, and there's no way to find out it's happening.

## How to fix it

Publish a DMARC TXT record at `_dmarc.<hostname>`, starting with `p=none` to monitor without affecting mail delivery. Review the aggregate reports it generates for a few weeks, then move the policy to `p=quarantine` and eventually `p=reject` once confident all legitimate mail is accounted for.
