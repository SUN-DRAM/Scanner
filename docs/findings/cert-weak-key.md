# Certificate uses a weak key

Certificate · High severity

## What it means

The certificate's cryptographic key is smaller than what's considered safe today — an RSA key under 2048 bits, or an ECDSA key under 256 bits.

## Why it matters

Key size determines how hard the private key is to break by brute force. Weak keys fall short of what modern browsers, PCI compliance, and most security audits expect, and some clients will actively refuse to negotiate a connection using one.

## How to fix it

Reissue the certificate with a stronger key: RSA 2048-bit or larger, or an ECDSA P-256 key. Every modern certificate authority issues these by default, so this is usually just a matter of regenerating the certificate signing request with the right key size and requesting a new certificate.
