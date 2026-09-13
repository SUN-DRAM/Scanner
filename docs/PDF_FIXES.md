# Fixes before the PDF ships

Three blockers found by reading the actual output. The PDF rendering layer is good — typography, page breaks, footers, memory profile all fine. These are correctness problems behind it.

Work them in order. Stop after each and show me.

---

## Fix 1 — `localhost:3000` in every finding link

Both generated PDFs end every finding with `http://localhost:3000/docs/findings/...`. Dead links, and to a prospect it reads as unfinished software.

Find where the PDF builds that absolute URL and confirm it uses `PUBLIC_BASE_URL` from §4. Then check what that variable is actually set to in the environment that generated these — if the PDFs came off the production stack, production's `.env` is wrong and the fix is on the server, not in code.

Add a test asserting no rendered URL contains `localhost` or `127.0.0.1`. This is the kind of thing that only gets caught by looking at output, and I'd rather it be caught by a test next time.

---

## Fix 2 — A+ awarded while four of seven checks failed (the serious one)

The `sundram.tech` report shows **A+, score 98/100** with Certificate, Chain, TLS and Security headers all reading "This check did not complete." The readiness module shows **A+** alongside "Could not be determined."

Contract §9 step 2 makes this arithmetically correct — errored modules are dropped and the remaining weights re-normalised, leaving only DNS (8) and email auth (8). But that rule was written for one module failing, and it does not hold when the load-bearing module fails. The result is a confidently wrong answer, which is precisely the failure mode this product exists to prevent. A certificate-monitoring company cannot ship an A+ report where the certificate check never ran.

### Contract amendment v3.0 — §9

Add after step 4:

**Step 4b — incompleteness overrides.**

- If the `certificate` module has `status: "error"` or `"skipped"`, **`overall_grade` and `overall_score` are `null`.** There is no grade. `headline` becomes a statement that the assessment could not be completed and why.
- If any module errored, the `Scan` object carries `is_complete: false` and `incomplete_modules: ["certificate", "tls", ...]` — new fields on §6.1.
- A module with `status: "error"` has **`grade: null`**, never a letter. It currently renders A+ for readiness when readiness could not be determined, which is the same bug one level down.
- Re-normalisation still applies when non-certificate modules error, but the result is always marked incomplete.

Mirror the new fields in `types/contract.ts` in the same edit.

### Presentation, everywhere the grade appears

Public result page, dashboard, and PDF all change together — one shared component, per the rule that already got broken once:

- Where the grade would be, show **"Incomplete"**, not a letter and not a blank
- A banner at the top: *"3 of 7 checks did not complete. This assessment is partial and should not be treated as a clean result."*
- Errored modules show "—" in the grade column
- The PDF's executive summary carries the same banner, prominently, above the module table

Tests: a scan with an errored certificate module returns a null grade; a scan with an errored readiness module shows no letter for it; the PDF renders the incomplete banner.

---

## Fix 3 — Find out why our own scan fails four modules

Four modules failed and two succeeded on `sundram.tech`. The four that failed all open a connection to the host. The two that worked only perform DNS lookups. That pattern points at the safety guard, not at the network.

My hypothesis: Step 0 added `OWN_PUBLIC_IPS = {"65.2.195.179"}` to `app/safety.py`, and `sundram.tech` resolves to that address — so every connecting module is rejected as a blocked target. The earlier fix replaced hostname-blocking with IP-blocking and reintroduced the same bug through a different route.

Verify before changing anything:

```bash
docker compose -f docker-compose.prod.yml exec api python -c "
from app.safety import resolve_and_validate
import asyncio; print(asyncio.run(resolve_and_validate('sundram.tech')))
"
```

**If confirmed, think carefully about the fix — the two requirements genuinely conflict.** §10 rule 8 requires blocking our own infrastructure, and that rule exists for a real reason: without it, the scanner can be pointed at our own internal surfaces. But we also must be able to scan our own public marketing site, since that's the credibility check the whole outreach plan rests on.

Propose a resolution that satisfies both, rather than deleting rule 8. An explicit allowlist for our own public hostnames, checked before the IP block, is the obvious shape — but state the residual risk of whatever you propose and let me approve it before you implement.

Whatever the outcome, add a test asserting a full seven-module scan of `sundram.tech` completes with no module in `error`. Our own self-scan silently degrading is not something we should ever learn about from a PDF.

---

## Polish, after the three above
- For our company name SUN-DRAM use the font "Playfair Display (Black)" and also increase the logo size , these both corrections are to be done in the front page
- **"A 83-day"** should be "An 83-day" — appears twice in the google.com report. Check the article logic wherever numbers are interpolated into prose.
- **Module summaries lead with the negative.** DNS grades A+ with the summary "DNSSEC is not enabled"; email auth grades A+ with "No DKIM selector responded." A reader sees a top grade beside what reads as a complaint. The summary should describe the module's overall state, with the info-level note secondary.
- **The readiness finding's evidence line repeats its own description** verbatim via `verdict_reason`. Drop duplicated text from the evidence block.
- **The logo has an off-white box baked into the SVG.** That's on me to re-export transparent, not something for you to edit — but confirm the renderer isn't adding a background of its own first.

---

Once Fixes 1–3 are done, regenerate both PDFs and send them again. And regenerate one for a domain with a genuinely bad grade — an F, a real expired certificate — because that's the report a prospect is most likely to receive, and it's the one neither sample tests.
