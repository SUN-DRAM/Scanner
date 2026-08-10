# No CAA record found

DNS · Low severity

## What it means

There's no CAA (Certification Authority Authorization) record for this hostname, so there's no DNS-level restriction on which certificate authorities are allowed to issue certificates for it.

## Why it matters

Without a CAA record, any certificate authority anywhere will issue a certificate for this domain to anyone who can pass its domain validation check. A CAA record is a cheap, low-effort control that closes off one avenue for a misissued certificate — most certificate authorities check it before issuing, and are required to honor it.

## How to fix it

Add a CAA record naming the certificate authority actually in use — for example: `0 issue "letsencrypt.org"`. If email or other services use different providers, add a CAA record for each one actually needed, and nothing more.
