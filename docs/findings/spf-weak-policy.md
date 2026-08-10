# SPF policy is too permissive

Email authentication · Low severity

## What it means

This domain's SPF record ends in `+all` or `?all`, which tells receiving mail servers to accept mail even from senders not listed in the record.

## Why it matters

An SPF record with a weak ending policy defeats much of the point of having one — it publishes a list of legitimate senders, then explicitly tells everyone else to accept mail from anyone else anyway. `+all` in particular is rarely intentional; it usually means the record was copied from an example without adjusting the last mechanism.

## How to fix it

Change the SPF record to end in `~all` (soft fail) or `-all` (hard fail). Start with `~all` while confirming the listed senders are complete and nothing legitimate gets flagged, then move to `-all` once confident.
