# Certificate is self-signed

Certificate · Critical severity

## What it means

The certificate is signed by itself, not by a certificate authority that browsers and operating systems trust. There's no chain of trust connecting it to anything a visitor's device already trusts.

## Why it matters

Every visitor sees a full-page security warning before they can reach the site, and most will leave rather than click through it. Self-signed certificates are fine for internal testing on a machine you control — they're not usable for anything public-facing.

## How to fix it

Replace it with a certificate from a trusted certificate authority. Let's Encrypt is free, works with almost every web server, and can be fully automated with an ACME client — there's rarely a good reason to keep a self-signed certificate on anything the public reaches.
