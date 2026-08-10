# Strict-Transport-Security header is missing

Headers · High severity

## What it means

The server doesn't send an HSTS (HTTP Strict Transport Security) header, so browsers have no instruction to always use HTTPS for this hostname.

## Why it matters

Without HSTS, a browser that's told to visit this site over plain HTTP — by a typed URL without `https://`, an old bookmark, or a malicious link — will try HTTP first, giving an attacker on the network a window to intercept that first request before any redirect happens. HSTS closes that window by telling the browser to never even attempt HTTP again, for as long as the header specifies.

## How to fix it

Add a `Strict-Transport-Security` header once HTTPS is confirmed working reliably across the whole site, for example: `max-age=31536000; includeSubDomains`. Don't add this before HTTPS is solid — HSTS is hard to walk back quickly once browsers have cached it.
