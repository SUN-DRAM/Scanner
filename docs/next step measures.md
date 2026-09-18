# Next steps — deploy, audit, then measure

Good diagnosis. The refutation was properly evidenced and you shipped the handshake sharing on its own merits rather than because a hypothesis needed it. Both correct calls.

Four things, in order.

---

## 1. Finish the teardown fix

`CONNECTION_CLOSE_TIMEOUT_SECONDS` was applied to `chain.py` only. `certificate.py` and `tls.py` open their own pinned connections too, and a peer that never sends `close_notify` will hang any of them the same way.

Audit every raw socket and SSL teardown in the scanner — `certificate.py`, `tls.py`, `safety.py`'s pinned-connection helper, and anywhere else a `writer.close()` / `wait_closed()` pair or equivalent exists. Bound each one with the same constant.

Fix the class, not the instance. A regression test for each module would have caught this shape once and for all.

---

## 2. Commit and deploy

Commit both fixes, then deploy to production with `scripts/deploy.sh`. Back up first.

After deploying, verify on the real box rather than locally:
- `/api/v1/health` returns 200
- A live scan of `honda.com` completes all seven modules
- A live self-scan of `sundram.tech` completes all seven modules

That last one matters: the self-scan has been failing from the dev container for weeks because of a known network path issue between that machine and `65.2.195.179`. From production it should be clean. If it isn't, that's a real problem and I want to know.

---

## 3. The 50-domain measurement — this is the decisive step

This is the number the whole project has been missing. Everything else has been chasing individual failures without knowing whether we're near done or nowhere close.

Build it as a repeatable script (`tests/accuracy/batch.py` or similar) so we can re-run it after any future change rather than guessing.

**Corpus:** 50 real domains of the kind we actually target — Indian digital agencies, their client sites, SMB SaaS, professional services. Not badssl fixtures, not tech giants, not typo domains. The hosts that would appear on a prospect's portfolio page.

**Pace it realistically** — a few per minute, not 50 at once. That's how bulk prospect scanning will actually run, so measure it that way.

**Report:**

| Metric | Why it matters |
|---|---|
| % of scans where all 7 modules complete | The headline number |
| % with ≥1 module errored | The inverse, for sanity |
| Breakdown by `ModuleErrorCode` | Tells us what to fix next |
| Which modules fail most | Same |
| Failures clustered by CDN, host, or ASN | Would revive the source-IP theory with real evidence |
| Median and p95 total scan duration | Contract §13 wants under 20s |
| How many failures a single retry would have rescued | Sizes the value of step 4 |

**Then re-run the same corpus once more, an hour later,** and report how many results changed. Stability matters as much as the rate — a scanner that returns different answers for the same host undermines trust faster than one that occasionally fails honestly.

**The decision gate:**
- **Above 95% clean** — we're done chasing. Ship step 4 and move on.
- **90–95%** — acceptable with retries. Ship step 4, note the residual, proceed.
- **Below 90%** — this is the only priority until it isn't. Report what's causing it and stop.

Do not tune anything to make the number look better. If it's 82%, I want to know it's 82%.

---

## 4. Handle the residue

Only after step 3, and sized by what it shows.

**4.1 — Retry once.** A connecting module that times out retries a single time after a short backoff before being declared errored. Confirm it fits the whole-scan budget and doesn't push p95 past 20 seconds.

**4.2 — Distinguish "we couldn't reach it" from "it's broken."** You framed this well yourself: `healthpowermedical.com`'s handshake fails identically from every vantage point, which is a real finding about their infrastructure, not a failure of ours. Right now we report it as "the check timed out", which understates a genuine problem and makes us look unreliable for something that isn't our fault.

Propose how to draw that line — a new finding code for an origin whose TLS is broken for all clients, versus a module error when we specifically can't reach something others can. Show me the proposal before implementing; it touches the findings catalogue and §8 is a closed set.

---

## A note on the flaky tests

You flagged `sundram.tech` unreachable and `badssl.com` transient as pre-existing and environmental, and verified the first with a raw socket connect that touches none of your code. Good — but both are network-marked tests that are now failing routinely for known reasons, and a test that always fails teaches people to ignore failures.

Either fix the environment, skip them with an explicit reason, or point them somewhere reachable. Don't leave them red.