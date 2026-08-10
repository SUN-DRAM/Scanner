# No SPF record found

Email authentication · Medium severity

## What it means

There's no SPF (Sender Policy Framework) record for this domain, so receiving mail servers have no published list of which servers are actually allowed to send email as this domain.

## Why it matters

Without SPF, it's straightforward for anyone to send email that claims to be from this domain — a common technique in phishing and business email compromise. It also hurts deliverability: many mail providers weigh SPF into spam filtering, so legitimate email from this domain is more likely to land in spam without it.

## How to fix it

Publish an SPF TXT record listing the mail services actually used to send email, for example: `v=spf1 include:_spf.google.com ~all`. List every legitimate sending service — the marketing platform, the transactional email provider, the office mail server — and nothing else.
