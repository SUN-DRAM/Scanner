# Permissions-Policy header is missing

Headers · Info severity

## What it means

The site doesn't send a `Permissions-Policy` header, so there's no explicit limit on which sensitive browser features — camera, microphone, geolocation, and others — embedded or third-party content on the page is allowed to request.

## Why it matters

This is a lower-urgency finding: most sites don't embed untrusted third-party content in a way that makes this exploitable. But wherever third-party scripts, ads, or iframes are present, a missing Permissions-Policy leaves the door open for them to request access to hardware features the site itself never uses.

## How to fix it

Add a `Permissions-Policy` header that turns off features the site doesn't use, for example: `Permissions-Policy: camera=(), microphone=(), geolocation=()`. Only allow what's actually needed, and only for the origins that need it.
