# Certificate uses a weak signature algorithm

Certificate · High severity

## What it means

The certificate is signed using SHA-1 or MD5, algorithms with known practical weaknesses against forgery.

## Why it matters

The signature is what proves the certificate authority actually issued this certificate and that it hasn't been tampered with. A weak signature algorithm undermines that guarantee — modern browsers have removed trust for SHA-1-signed certificates entirely, so this usually means the site is already broken for current browsers, not just at risk.

## How to fix it

Reissue the certificate. Every certificate authority issuing today signs with SHA-256 or stronger by default, so this almost always means the certificate is old and simply needs replacing, not that anything needs reconfiguring.
