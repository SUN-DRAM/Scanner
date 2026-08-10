# Server header discloses a version number

Headers · Low severity

## What it means

The `Server` header includes a specific software version number — for example `nginx/1.18.0` instead of just `nginx`.

## Why it matters

This doesn't create a vulnerability by itself, but it hands an attacker a shortcut: instead of probing for what software is running, they know exactly which version, and can go straight to checking it against known vulnerabilities for that specific release. It's a small piece of reconnaissance that costs nothing to remove.

## How to fix it

Configure the web server to omit its version number from the `Server` header (`server_tokens off;` in nginx, `ServerTokens Prod` in Apache), or remove the header entirely if the server supports that.
