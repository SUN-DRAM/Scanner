# X-Frame-Options header is missing

Headers · Low severity

## What it means

The site doesn't send an `X-Frame-Options` header, and its Content-Security-Policy (if it has one at all) has no `frame-ancestors` directive either. Nothing stops another site from loading this page inside a frame.

## Why it matters

This is the basis of clickjacking: an attacker embeds this page in an invisible or disguised frame on their own site, and tricks a visitor into clicking something that actually clicks a button on the framed page underneath — a "confirm transfer" or "grant access" button the visitor never meant to click.

## How to fix it

Add `X-Frame-Options: DENY` (or `SAMEORIGIN` if the site legitimately frames its own pages), or a CSP `frame-ancestors` directive, which supersedes `X-Frame-Options` in browsers that support it and offers finer control over which origins are allowed to frame the page.
