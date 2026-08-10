# Connection doesn't use forward secrecy

TLS · Medium severity

## What it means

The cipher suite the server negotiated doesn't provide forward secrecy — it doesn't use ECDHE or DHE key exchange to generate a unique key for each session.

## Why it matters

Forward secrecy means that even if the server's private key is ever exposed — through a breach, a misconfiguration, or a subpoena — past encrypted traffic stays unreadable, because each session used its own throwaway key rather than one derived directly from the long-term private key. Without it, a single key compromise can retroactively expose everything ever recorded.

## How to fix it

Prioritise ECDHE or DHE cipher suites in the server's TLS configuration so every session negotiates its own key. Nearly every modern cipher suite list defaults to this already, so this usually means an old or custom cipher configuration needs updating.
