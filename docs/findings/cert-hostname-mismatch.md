# Certificate doesn't cover this hostname

Certificate · Critical severity

## What it means

The certificate this hostname presents doesn't list it — not in the certificate's common name, and not in its subject alternative names (SANs). The certificate might be perfectly valid for some other hostname; it just isn't valid for this one.

## Why it matters

Browsers check that the certificate actually names the site being visited, specifically to stop one certificate being reused to impersonate another site. When it doesn't match, every visitor sees a name-mismatch warning — one of the more alarming ones browsers show, because it looks like exactly the kind of attack this check exists to catch.

## How to fix it

Reissue the certificate with this hostname included in its subject alternative names. This commonly happens after adding a new subdomain, migrating to a new server, or pointing DNS at infrastructure that's serving a certificate meant for a different domain — check which of those changed most recently.
