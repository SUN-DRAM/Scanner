# HTTP doesn't redirect to HTTPS

Headers · High severity

## What it means

Visiting this hostname over plain HTTP doesn't redirect to HTTPS — the server is willing to serve the site unencrypted.

## Why it matters

Anyone who types the address without `https://`, follows an old link, or has software that defaults to HTTP stays on an unencrypted connection, fully exposed to anyone on the network path. This is also the most common way HSTS never gets a chance to help: a browser has to be redirected to HTTPS at least once before it can even learn to enforce it going forward.

## How to fix it

Add a server-level redirect from HTTP to HTTPS so no visitor is ever served the site unencrypted, regardless of how they arrived. This is typically a few lines of configuration in the web server or load balancer, and is safe to add immediately — unlike HSTS, it doesn't get cached by the browser.
