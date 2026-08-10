# Certificate expired

Certificate · Critical severity

## What it means

The TLS certificate serving this hostname has passed its expiry date. The window of trust it was issued for has closed.

## Why it matters

Browsers and API clients don't show a warning and let people click through — they refuse the connection outright. Every visitor, every mobile app call, every server-to-server integration hitting this hostname over HTTPS stops working the moment the certificate expires. There's no grace period.

## How to fix it

Renew the certificate now, and confirm the new one is actually being served — don't just trust that renewal ran. An expired certificate almost always means an automated renewal job failed silently once already, weeks before you noticed. Fix the renewal process itself, not just this one certificate, or you'll be back here in another 90 days.
