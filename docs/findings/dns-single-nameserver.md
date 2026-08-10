# Only one nameserver is configured

DNS · Medium severity

## What it means

This domain has a single authoritative nameserver answering for it, instead of the two or more that DNS is designed to expect.

## Why it matters

DNS redundancy exists precisely so a single outage doesn't take a domain offline. With only one nameserver, if that one server or network becomes unreachable — an outage at the DNS provider, a network issue, a misconfiguration — the domain stops resolving for everyone, everywhere, until it's fixed.

## How to fix it

Add at least one more nameserver. Where possible, use a second provider or network entirely rather than another server from the same provider, so a single provider-wide outage doesn't still take the whole domain down.
