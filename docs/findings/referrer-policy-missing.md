# Referrer-Policy header is missing

Headers · Low severity

## What it means

The site doesn't send a `Referrer-Policy` header, so the browser falls back to its own default behavior for deciding how much of this site's URLs get sent to other sites when a visitor clicks an outbound link.

## Why it matters

URLs often contain more than a visitor realizes — session identifiers, search terms, internal paths, sometimes account-related tokens. Without an explicit policy, that full URL can leak to whatever site a link points to, entirely outside this site's control.

## How to fix it

Add a `Referrer-Policy` header — `strict-origin-when-cross-origin` is a sensible, widely-supported default that sends the full URL to same-site requests but only the origin to cross-site ones.
