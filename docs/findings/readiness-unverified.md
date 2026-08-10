# Renewal automation couldn't be confirmed

Readiness · Medium severity

## What it means

This certificate's lifetime is 100 days or under — short enough to suggest an automated renewal process — but it wasn't issued by a certificate authority this scan recognizes as an ACME provider (Let's Encrypt, ZeroSSL, Google Trust Services, Buypass). It might well be automated through a different provider; the scan just can't confirm that from the issuer name alone.

## Why it matters

A short certificate lifetime is a strong hint of automation, but not proof — some certificate authorities support ACME under a less recognizable issuer name, and it's also possible to manually reissue a short-lived certificate on a schedule. Since the March 2027 change makes automated renewal effectively mandatory for anyone not wanting to renew every few weeks by hand, it's worth confirming which case this actually is.

## How to fix it

Confirm directly whether renewal for this certificate is actually automated. If it is, no action is needed — this finding only means the scan couldn't verify it from the issuer name, not that anything is actually wrong. If it turns out renewal isn't automated, treat it the same as a manual renewal process and move to an ACME client before March 2027.
