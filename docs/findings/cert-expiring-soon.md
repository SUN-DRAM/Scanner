# Certificate expires soon

Certificate · High severity

## What it means

This certificate has between 4 and 14 days left before it expires.

## Why it matters

This is the window where renewal needs to actually happen — most renewal processes (including ACME clients like Certbot) are designed to trigger around day 30, which means if nothing has renewed by now, the automation may not be running at all rather than just running late.

## How to fix it

Set up automated renewal if it isn't already running, or renew manually now and don't wait for it to get closer. Either way, add expiry alerts at 30, 14 and 7 days so a future renewal failure gets caught long before it becomes urgent.
