# Legacy TLS protocol is enabled

TLS · High severity

## What it means

The server still accepts connections using TLS 1.0 or TLS 1.1.

## Why it matters

Both protocols have known cryptographic weaknesses, and every major browser has removed support for them — so keeping them enabled doesn't help any real, current visitor. What it does do is widen the attack surface: it gives an attacker on the network path an older, weaker protocol to try to downgrade a connection to, and it's a routine finding in security audits and PCI compliance scans.

## How to fix it

Disable TLS 1.0 and TLS 1.1 in the server's TLS configuration, keeping TLS 1.2 and TLS 1.3 only. This is almost always a single configuration change (for example `ssl_protocols` in nginx, or `SSLProtocol` in Apache) with no impact on real traffic, since current browsers and API clients have used TLS 1.2+ by default for years.
