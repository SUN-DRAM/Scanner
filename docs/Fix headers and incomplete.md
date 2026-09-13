# Fix — headers module failing, and incomplete scans reported badly

Two things: a module that consistently fails on a real prospect domain, and the fact that we can't tell *why* without SSH access — which is the deeper problem.

Work them in order. Stop after step 1 and show me what you found before fixing anything.

---

## Step 1 — Diagnose, don't guess

`letshego.com` produces `1 of 7 checks did not complete` on every attempt. The headers module is the one failing. It reproduces consistently, so this is not a transient timeout.

**Reproduce it and capture the actual exception** — type, message, and traceback. Run `safe_get` against that host directly, outside the module's exception handling, so nothing is swallowed:

```bash
docker compose exec api python -c "..."
```

Then compare against `curl` from inside the same container, with the same browser User-Agent the scanner now sends:

```bash
curl -sIL -A "<our UA>" http://letshego.com
curl -sIL -A "<our UA>" https://letshego.com
curl -sI --http1.1 https://letshego.com
curl -sI --tlsv1.2 --tls-max 1.2 https://letshego.com
```

Candidate causes, in rough order of likelihood — check rather than assume:

- **Timeout.** The module has an 8-second budget. A slow origin, or a long redirect chain where each hop is slow, blows it. Measure the actual wall time `curl` takes.
- **Redirect behaviour.** Contract §10 rule 4 allows at most 5 hops with revalidation at each. A loop, a cookie-gated redirect, or a hop to a host that fails the safety check would abort the whole module rather than degrade.
- **WAF or bot protection.** Same class as the swiggy.com CloudFront bug — but that was fixed with the browser User-Agent, so if this is a WAF it's a different one with stricter fingerprinting (TLS JA3, header ordering, HTTP/2 vs 1.1).
- **TLS or HTTP incompatibility between httpx and an older origin** — HTTP/2 negotiation, an unusual cipher, or a server that mishandles `Accept-Encoding: br`.
- **Response size.** Rule 6 caps reads at 512KB. Confirm hitting that cap degrades gracefully rather than raising.
- **IPv6.** If the host has AAAA records and we prefer IPv6, and the container's IPv6 path is broken, every connection fails while `curl` on IPv4 succeeds.

Report the actual cause with evidence. If it turns out to be something outside our control — the origin genuinely refusing us — say so plainly and we'll decide how to present that, rather than pretending we can fix it.

---

## Step 2 — Fix the root cause, and the class of bug

Once you know what it is, fix it — but fix the category, not just this hostname.

If it's a timeout, ask whether 8 seconds is right for a module that may follow five redirects, and whether a partial result (we reached the final URL but ran out of time reading) should still yield headers rather than nothing.

If it's a redirect or safety abort, the module should degrade to reporting what it *did* observe rather than returning nothing at all.

Whatever the cause, add `letshego.com` to the network-marked accuracy corpus with an assertion that the headers module completes.

**Then check the other 20 domains from the grading validation run** and report how many have any module in `error`. If it's more than one or two, this is a systemic gap and I want to know the rate before we send reports to anyone.

---

## Step 3 — We should not need SSH to answer "why did it fail"

This is the real lesson. A module that fails swallows the exception into `status: "error"` and the `Scan` object carries no usable explanation, so the only way to diagnose is to shell into production and re-run by hand. That doesn't scale past one person and it won't work at all once customers are asking.

Populate `ModuleResult.error` (contract §6.2, currently unused in this path) with a structured, safe explanation:

```jsonc
"error": {
  "code": "MODULE_TIMEOUT",
  "message": "The security headers check timed out after 8 seconds."
}
```

A small closed set of codes — `MODULE_TIMEOUT`, `CONNECTION_REFUSED`, `CONNECTION_RESET`, `TLS_ERROR`, `TOO_MANY_REDIRECTS`, `BLOCKED_REDIRECT_TARGET`, `HTTP_ERROR`, `UNEXPECTED_ERROR` — added to `enums.py` and `contract.ts` in lockstep, and documented in the contract.

**The `message` is user-facing, so no tracebacks, no internal hostnames, no library names, no stack details.** The full exception goes to the application log against the `request_id`, never into the response.

Bump the contract and record it in the amendment log.

---

## Step 4 — Present incomplete scans honestly

Three changes to how a partial result is displayed. All three apply to the public result page, the dashboard, and the PDF, through the shared components.

**4.1 — Name the failed check.** The banner currently reads *"1 of 7 checks did not complete."* We added `incomplete_modules` to the contract in v3.0 precisely so it could say which. Render it:

> **1 of 7 checks did not complete: security headers.** This assessment is partial and should not be treated as a clean result.

When step 3 lands, append the reason where we have one: *"— the check timed out."*

**4.2 — Don't show a precise score for an incomplete scan.** A module that didn't run produces no findings, so it contributes nothing to the global deduction and its weight redistributes to the modules that passed. The score is therefore **biased upward by an unknown amount** — `letshego.com`'s 81 could really be 70 if the headers check had completed.

Showing "81/100" next to a warning that the result is partial is the same error we just fixed with grade-versus-score: displaying a precise number the data doesn't support.

Show the grade letter with the caveat, and present the score as a ceiling — "81 or lower" — or suppress the number entirely. Pick one, apply it everywhere, and say which you chose and why.

**4.3 — The module card for a failed module** should show the reason from step 3, not just a dash. A user looking at the detail should be able to see "timed out" without asking us.

---

## Step 5 — Two small ones, while you're here

**Timezone inconsistency.** The web result page prints `15:37 UTC`; the PDF prints `IST (UTC+05:30)`. Standardise on IST with the offset shown, in both. Our market is India.

**Suppress the reduction line on top grades.** `sundram.tech` reads *"A+ · Score 98/100 · A+ — reduced by 2 low-severity findings."* Saying a top grade was "reduced" undercuts it. Only show that line when the deductions actually cost the site a band — so not for A+, and not for A where the raw weighted score was already in that band.

---

## Verification

- `letshego.com` scans with all seven modules completing, and the result is stable across three consecutive runs
- A deliberately unreachable target produces a module error with a correct code and a safe, readable message
- No traceback, internal hostname, or library name appears in any API response
- The incomplete banner names the module and the reason
- The score presentation for an incomplete scan matches whatever you chose in 4.2, on all three surfaces
- Full suite green, and the error-path tests actually assert on the response body rather than just the status.