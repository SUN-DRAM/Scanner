# Certificate chain ends in an untrusted root

Chain · Critical severity

## What it means

The root certificate at the top of the chain isn't one of the roots that browsers and operating systems ship with as trusted by default.

## Why it matters

The whole point of a certificate chain is to trace back to a root that the visitor's device already trusts. If it ends somewhere else, that chain of trust never actually connects — visitors see the same kind of hard security warning as an expired or self-signed certificate, regardless of how correctly everything else about the certificate is configured.

## How to fix it

Reissue the certificate from a certificate authority whose root is trusted by major browsers and operating systems. This most often happens with an internal or self-hosted certificate authority being used for a public-facing hostname by mistake, or a very old root that's since been removed from modern trust stores.
