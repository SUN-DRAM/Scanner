# SPF record needs too many DNS lookups

Email authentication · Medium severity

## What it means

Evaluating this domain's SPF record requires more than 10 DNS lookups — over the limit the SPF standard (RFC 7208) allows.

## Why it matters

This limit exists to stop SPF checks from becoming a denial-of-service vector, and mail servers enforce it strictly: once a record needs more than 10 lookups, the standard says to treat the whole check as a permanent error, not as a pass. That means SPF is effectively broken for this domain, which can hurt deliverability the same way a missing record does.

## How to fix it

Flatten or trim the SPF record — combine `include:` mechanisms where possible, and remove ones for services no longer in use, to bring the total lookup count under 10. Each `include`, `a`, `mx`, `ptr` and `exists` mechanism counts toward the limit, and `include`s can nest, so the real count is often higher than it looks from reading the record alone.
