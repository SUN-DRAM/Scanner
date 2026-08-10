# OCSP stapling isn't enabled

Certificate · Low severity

## What it means

The server doesn't staple an OCSP (Online Certificate Status Protocol) response during the TLS handshake — it doesn't proactively hand the browser proof that the certificate hasn't been revoked.

## Why it matters

Without stapling, some browsers check revocation status separately, by contacting the certificate authority directly. That adds a small delay to every connection, and it leaks to the certificate authority which sites a visitor is checking — a minor but real privacy cost that stapling avoids entirely.

## How to fix it

Enable OCSP stapling in the web server's TLS configuration. Most modern servers (nginx, Apache, Caddy) support it with a single configuration directive, and it's safe to turn on with no other changes needed.
