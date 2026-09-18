# Fix — too many connections per scan

`honda.com` scanned with only the **Chain** module failing. `homda.com` failed Chain, TLS and Security headers. Earlier failures showed the same shape: modules that open a connection fail, modules that only do DNS succeed.

**Hypothesis: we open far too many TCP connections to a single host, concurrently, and protective infrastructure drops the later ones.**

Chain failing while Certificate succeeded is the tell. Both derive from the same TLS handshake — if the certificate came back, the chain was in that same response. Chain can only fail independently if it makes its own separate connection.

Diagnose first. Do not change code in step 1.

---

## Step 1 — Count the connections

Instrument or trace a single scan of one hostname and report **exactly how many TCP connections it opens to that host, and when.**

My estimate, to be confirmed or corrected:

| Module | Connections | Why |
|---|---|---|
| certificate | 1 | handshake |
| chain | 1 | separate handshake for data already retrieved |
| tls | 4 | one per protocol version probed |
| headers | 2 | http then https |

That would be about eight, fired near-simultaneously via `asyncio.gather`. From a datacenter IP that resembles a port scan closely enough for a WAF, CDN, or SYN-flood protection to start dropping packets — which produces silent timeouts, not refusals, matching what we see.

Also capture:
- Whether the connections are concurrent or staggered, and over what window
- Which modules open connections at all (`packet capture` or socket-level logging, not inference from code)
- Whether the ones that fail are consistently the later ones

**Then test the hypothesis directly.** Scan `honda.com` twice: once normally, once with the modules forced to run strictly serially with a 1–2 second gap between each. If the serial run completes cleanly and the concurrent one doesn't, the diagnosis is confirmed and the cause is ours.

---

## Step 2 — Fix, if confirmed

Three changes, in order of value:

**2.1 — Share one handshake between certificate and chain.** This is the clear win: two modules doing the same handshake for data that arrives together. Perform it once, pass the result to both. Halves the most expensive part of the scan and removes an entire failure mode.

Keep the modules separate in the output — contract §6.4 defines `certificate.data` and `chain.data` distinctly, and that shouldn't change. Only the connection is shared.

**2.2 — Rethink the TLS version probes.** Four connections purely to establish which protocol versions are supported is a large share of our footprint. Options to evaluate:
- Reuse the shared handshake for the negotiated version and probe only the others
- Stagger the probes rather than firing them together
- Probe only what the findings actually need: `TLS_LEGACY_PROTOCOL` needs to know whether 1.0 or 1.1 are accepted, and `TLS_NO_TLS13` whether 1.3 is. That may be two probes, not four.

Don't lose accuracy to save a connection. If four probes are genuinely required, say so and we stagger instead.

**2.3 — Pace the remaining connections.** A small delay between connections to the same host, so a scan looks like a browser rather than a scanner. Measure the effect on total scan time — contract §13 wants a result inside 20 seconds and that still matters, because the public scanner is the acquisition channel.

---

## Step 3 — Measure the improvement

Re-run the 50-domain batch from `FIX_SCAN_RELIABILITY.md` step 3 before and after, and report:

- Clean-scan rate before and after
- Median and p95 scan duration before and after
- Whether any domain that previously failed still fails, and why

**Target: above 95% clean.** If the change takes us there without pushing scan time past 20 seconds, ship it. If it improves reliability but makes scans noticeably slower, show me both numbers and I'll decide the trade-off — don't make that call silently.

---

## Step 4 — Handle the residue

Some hosts will still refuse us, and we should stop treating every one as a scanner defect.

**4.1 — Retry once.** A connecting module that times out retries a single time after a short backoff before being declared errored. Confirm this fits the whole-scan budget.

**4.2 — Distinguish "we couldn't reach it" from "it's broken."** `healthpowermedical.com` has a genuinely broken TLS origin — that's a real finding about their infrastructure and worth reporting as such. `bytemotion.com` blocks datacenter IPs — that's about us, not them. Right now both render as "the check timed out," which is accurate but unhelpful and, in the first case, understates a real problem.

Consider whether `TLS_ERROR` on a handshake the origin actively rejects should be a finding rather than a module error. A site whose TLS fails for every client has something genuinely wrong with it, and saying so is more useful than saying our check didn't finish.

---

Start with step 1. The serial-versus-concurrent test is the fastest way to confirm or kill this, so do that early.