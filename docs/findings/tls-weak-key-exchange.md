# Key exchange uses weak parameters

TLS · High severity

## What it means

The connection negotiated a Diffie-Hellman key exchange (DHE) with fewer than 2048 bits, or an elliptic-curve key exchange (ECDHE) with a curve smaller than 256 bits.

## Why it matters

The key exchange is what gives TLS forward secrecy — a fresh, disposable key for every session, so a stolen private key can't decrypt traffic recorded in the past. A weak key exchange narrows the effort needed to break that protection for a captured session, even though the connection is technically "encrypted."

## How to fix it

Configure the server to offer only DHE groups of 2048 bits or larger, or ECDHE curves of 256 bits or larger (X25519 or P-256 are the current defaults on every major web server). Most modern servers already default to safe groups — this finding usually means an explicit legacy override is still in place.

## A note on this check

Determining the exact bits or curve actually negotiated requires reading past what this scanner's TLS library exposes. Where that isn't possible, this scan reports what it can verify (whether DHE or ECDHE was used) and leaves the rest unknown rather than guessing — an unverified key exchange never produces this finding on its own.
