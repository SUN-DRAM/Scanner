# Certificate is not valid yet

Certificate · Critical severity

## What it means

The certificate's start date is in the future. Right now, today, it isn't valid — even though it will be eventually.

## Why it matters

Browsers treat a not-yet-valid certificate exactly like an expired one: a hard security warning, no exceptions. Visitors can't reach the site until the start date arrives, or until the underlying problem is fixed.

## How to fix it

This is almost always one of two things: a server clock that's set wrong, or a certificate that was issued with the wrong validity period. Check the server's system time first — a clock even a few hours off can trigger this. If the clock is correct, check the certificate's actual "not before" date with the issuing certificate authority and reissue if it's wrong.
