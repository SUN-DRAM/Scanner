# Content-Security-Policy header is missing

Headers · Medium severity

## What it means

The site doesn't send a Content-Security-Policy (CSP) header, so the browser has no restriction on which scripts, styles, images or frames the page is allowed to load.

## Why it matters

CSP is the main browser-level defense against cross-site scripting turning into real damage. Without it, if an attacker ever manages to inject a script into the page — through an unsanitized input field, a compromised third-party script, or a vulnerable dependency — the browser will run it without question, and it can do anything the page's own scripts can do: read cookies, submit forms, exfiltrate data.

## How to fix it

Start with a reporting-only Content-Security-Policy (`Content-Security-Policy-Report-Only`) to see what the site actually loads without breaking anything, then tighten it into an enforcing policy once the report data shows what's genuinely needed.
