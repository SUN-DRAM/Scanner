# Certificate uses a weak signature algorithm

Certificate · High severity

## What it means

A certificate in the chain — the leaf or an intermediate — is signed using SHA-1 or MD5, algorithms with known practical weaknesses against forgery. This check covers every certificate presented except the root: a root's signature is over itself, and it's trusted by identity rather than by that signature, so it carries no security meaning either way.

## Why it matters

The signature is what proves the certificate authority actually issued this certificate and that it hasn't been tampered with. A weak signature algorithm undermines that guarantee — modern browsers have removed trust for SHA-1-signed certificates entirely, so this usually means the site is already broken for current browsers, not just at risk. A weak intermediate is exactly as fatal as a weak leaf: browsers validate every link in the chain, not just the one closest to the site.

## How to fix it

Reissue the affected certificate. Every certificate authority issuing today signs with SHA-256 or stronger by default, so this almost always means the certificate is old and simply needs replacing, not that anything needs reconfiguring. If the finding names an intermediate rather than the leaf, that's the certificate authority's chain to update — contact them for a current bundle.
