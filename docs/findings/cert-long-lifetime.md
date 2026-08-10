# Certificate lifetime is long

Certificate · Medium severity

## What it means

This certificate was issued for longer than 200 days.

## Why it matters

The CA/Browser Forum — the body that sets the rules certificate authorities and browsers agree to follow — is phasing maximum certificate lifetimes down: 200 days from 15 March 2026, 100 days from 15 March 2027, and 47 days from 15 March 2029. A certificate this long won't be issuable much longer, and a manual, calendar-driven renewal process that works fine every year or two starts breaking down once it needs to happen every 47–100 days.

## How to fix it

Move to a certificate authority and renewal workflow built for short lifetimes — an automated ACME client (Certbot, acme.sh, or your infrastructure platform's built-in support) with Let's Encrypt, ZeroSSL, Google Trust Services or Buypass. Once renewal is automated, a shorter lifetime stops being a problem and starts being the safer default — a compromised or misissued short-lived certificate has far less time to do damage.
