# TLS 1.3 isn't supported

TLS · Low severity

## What it means

The server doesn't negotiate TLS 1.3 — connections fall back to TLS 1.2, which still works fine but isn't the current standard.

## Why it matters

TLS 1.3 is both faster (fewer round trips to establish a connection) and more secure (it removes several legacy cryptographic options that TLS 1.2 still permits). This isn't an active vulnerability — TLS 1.2 is still considered secure — it's a missed, essentially free upgrade.

## How to fix it

Enable TLS 1.3 in the server's TLS configuration. Most modern web servers and load balancers support it already; it's frequently just a version string away from being turned on, with no compatibility downside for real-world clients.
