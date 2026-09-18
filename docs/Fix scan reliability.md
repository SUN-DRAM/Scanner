# Fix — systemic scan failures at outreach volume

Four prospect domains failed to scan fully during outreach today. `healthpowermedical.com`,'bytemotion.com' returned 5 of 7 modules errored, and `irctc.co.in` has been failing for hours.

The pattern is consistent and diagnostic: **every module that opens a TCP connection fails (certificate, chain, TLS, headers, and readiness which depends on certificate); the two that only perform DNS lookups succeed.** This is not a per-domain quirk. Something is stopping us connecting.

This is now the biggest operational risk to the business — a report we can't complete is a prospect we can't contact.

**Diagnose before fixing. Do not change code in step 1.**

---

## Step 1 — Establish what's actually happening

### 1.1 Characterise the failure

For `healthpowermedical.com` and the other three failed domains, from **inside the production container**, capture for each:

- The `ModuleErrorCode` for every errored module (we have structured errors now — use them)
- Whether TCP connect succeeds, and how long it takes
- Whether the TLS handshake completes
- Whether an HTTP response ever arrives
- Total wall time before the timeout fires

Distinguish clearly between: connection refused, connection reset, SYN silently dropped (hangs until timeout), TLS handshake rejected, and a response that arrives too slowly. **These have completely different causes and the fix depends on which it is.**

### 1.2 Test the same domains from a different vantage point

This is the decisive test. Run the same checks from:

- Your local machine on a residential connection
- Any non-AWS host you can reach

```bash
curl -svI --max-time 20 https://healthpowermedical.com
openssl s_client -connect healthpowermedical.com:443 -servername healthpowermedical.com
```

**If they succeed from a residential IP and fail from the EC2 box, the cause is our source IP, not the target.** That's a different problem with different fixes, and it's my leading hypothesis: many WAFs and CDNs treat datacenter address space as bot traffic and either challenge it or drop it silently. Bulk scanning from one address during outreach makes that worse.

If they fail everywhere, the origins are genuinely slow or hostile and the fix is in our timeout and retry behaviour.

### 1.3 Identify what's in front of these domains

For each failed domain, determine the CDN or WAF — Cloudflare, Akamai, Imperva, AWS WAF, Sucuri — from DNS, IP ownership, and any response headers you can get. If the four failures share a provider, that's the answer.

### 1.4 Rule out our own box

High-volume outbound scanning on a small instance can exhaust resources in ways that look exactly like remote blocking. Check on the production host:

```bash
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
ss -s
sysctl net.ipv4.ip_local_port_range
dmesg -T | tail -50
```

Also check the `unbound` container — if DNS resolution is slow, every connection inherits that delay before the module's own budget starts.

**Report findings with evidence. Do not proceed to step 2 until we know which of these it is.**

---

## Step 2 — Fix, once we know the cause

Likely shapes, depending on what step 1 shows. Don't pre-commit to any of these.

**If it's source-IP reputation:** we need a scanning strategy that doesn't look like abuse. Rate-limit outbound scans per destination and globally, add realistic connection behaviour, and consider whether bulk prospect scanning should run slowly in the background over hours rather than firing concurrently. A second vantage point is possible but adds real complexity — cost it before recommending it.

**If it's timeouts on slow origins:** the 8-second per-module budget may be too tight for origins behind slow CDNs. But raising it globally slows every scan including the interactive public one, which is the acquisition channel. Consider a longer budget for scheduled and bulk scans than for interactive ones.

**If it's our own resource limits:** tune conntrack and ephemeral port range, and cap outbound concurrency properly.

**Regardless of cause, add automatic retry for connecting modules.** A single transient failure currently produces a permanently incomplete scan. Retry the connecting modules once, after a short backoff, before declaring the module errored. Confirm this doesn't blow the whole-scan budget.

---

## Step 3 — Measure the real failure rate

I've been judging this from four anecdotes. I need a number.

Run a batch across 50 real domains of the kind we actually target — Indian agencies, SMB sites, the kind of hosts on a prospect's portfolio page — and report:

- Percentage of scans where all seven modules complete
- Percentage with at least one connecting module errored
- Breakdown by `ModuleErrorCode`
- Whether failures cluster by CDN or hosting provider
- Whether a retry would have rescued them

**If the clean-scan rate is below about 90%, outreach is not viable yet** and this becomes the priority over everything else. If it's above 95%, it's an edge case we handle with retries and re-scanning.

Add this batch as a repeatable script so we can re-measure after changes rather than guessing.

---

## Step 4 — Two product changes for incomplete scans

**4.1 — Don't offer a PDF for a scan with no grade.** The result page for `healthpowermedical.com` shows "Incomplete", no grade, and a Download PDF report button. That PDF would be a branded document with nothing in it. Contract §7.14 already says no PDF for `status != "completed"`; extend that to `is_complete: false` where `overall_grade` is null. Hide the button and explain why.

**4.2 — Add re-scan on the result page.** When a scan is incomplete, the user's only option is to go back and retype the hostname. Add a "Scan again" action that re-runs it, with the existing rate limit applied.

---

## Also, unrelated but quick

Add a second line to the `READINESS_MANUAL_2027` remediation:

> Automating renewal is the first step. The failure mode that actually causes outages is a renewal that stops working silently — a rebuilt server, an expired API token, a DNS change. Whatever client you choose, monitor that it's still renewing.

Honest, useful, and it names the real risk rather than stopping at "use an ACME client."

---

Start with step 1. Evidence first.