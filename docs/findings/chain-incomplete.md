# Certificate chain is missing intermediates

Chain · High severity

## What it means

The server presents its own certificate but not the full chain of intermediate certificates connecting it up to a trusted root.

## Why it matters

Desktop browsers often paper over this — they cache intermediates from other sites and quietly fill in the gap, so the site can look completely fine when you check it yourself. Most other clients don't get that help: curl, mobile apps, payment SDKs, and server-to-server integrations will fail to validate the connection outright. This is one of the most common causes of "it works in my browser but our integration is broken" reports.

## How to fix it

Configure the server to serve the full intermediate chain, not just the leaf certificate. The certificate authority that issued the certificate publishes the correct intermediate bundle for it — most ACME clients and hosting platforms handle this automatically, so this usually points to a manual or non-standard TLS setup.
