# X-Content-Type-Options header is missing

Headers · Low severity

## What it means

The site doesn't send `X-Content-Type-Options: nosniff`, so browsers are left free to guess a file's content type rather than trusting the type the server declared.

## Why it matters

Older browsers' MIME-sniffing behavior — trying to guess what a file "really is" regardless of its declared type — has historically been used to smuggle scripts past upload filters and content-type checks, by disguising a script as something more innocuous. `nosniff` turns that guessing off.

## How to fix it

Add `X-Content-Type-Options: nosniff` to every response. This is a single header with no compatibility downside — safe to add everywhere, immediately.
