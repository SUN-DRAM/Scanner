# Certificate chain is out of order

Chain · Medium severity

## What it means

The server sends its certificates in the wrong sequence — the leaf certificate, intermediates and root aren't in the order clients expect.

## Why it matters

Many clients tolerate this and reassemble the chain regardless. Stricter ones don't — this shows up disproportionately on mobile TLS libraries and IoT/embedded devices, which tend to implement the bare minimum of chain-building logic and simply fail rather than sort things out.

## How to fix it

Reorder the certificate bundle: leaf certificate first, followed by intermediates in order, ending with (or just before) the root. Most web servers read the chain file top to bottom in exactly this order, so this is usually a matter of fixing how the bundle file was assembled.
