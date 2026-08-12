Gate A follow-ups — run before Gate B

**Status (2026-08-11): all five items (A1–A5) closed.** A1 shipped with CONTRACT.md v1.2. A2–A5 shipped with CONTRACT.md v1.4, ahead of Gate C — see the v1.4 amendment-log entry for what changed, `apps/api/tests/test_grading.py` / `test_tls_classifiers.py` / `test_findings.py` for the new test coverage, and `apps/api/pyproject.toml` / `tests/conftest.py` for A3's network-marker mechanism.

Gate A passed. Five items came out of it. A1 is a suspected bug and blocks Gate B. A2–A5 are contract amendments and hygiene, and can ship alongside it.

A1 — Verify the five unverified modules (BLOCKING)

Gate A cross-checked the certificate and dns modules against independent tooling and found zero discrepancies. It did not cross-check headers, tls, chain, email_auth, or readiness against anything, but the A2 table records header findings as verified. Close that gap.

Suspected bug, check this first. The report has google.com producing HSTS_MISSING and NO_HTTPS_REDIRECT. Verify against curl -sIL http://google.com and curl -sI https://www.google.com. My expectation is that Google does serve HSTS, which would make our finding wrong.

The likely cause: http://example.com redirects to https://www.example.com — a different hostname. If the headers module stops at the first hop, or follows the chain but then evaluates headers against the originally-requested host rather than the final URL, every apex domain that redirects to www gets a false HSTS_MISSING and possibly a false NO_HTTPS_REDIRECT. That is most of the internet and most of our buyers. It would also mean the flipkart.com and swiggy.com results in the Gate A report are wrong, and those are exactly the results we would put in a prospect email in week 3.

Decide and document the intended semantics explicitly in CONTRACT.md §6.4: when the redirect chain crosses to a different hostname, headers are evaluated on the final URL, and final_url in the response makes that visible. Then make the code match.

Extend the A3 cross-check to cover all seven modules across the same ten domains:

headers → curl -sIL, checking the full redirect chain and which hop each header came from
tls → openssl s_client -tls1 / -tls1_1 / -tls1_2 / -tls1_3 per protocol, and nmap --script ssl-enum-ciphers if available
chain → openssl s_client -showcerts, confirming chain length, order and root
email_auth → dig TXT for SPF and _dmarc, and the DKIM selectors we probe
readiness → arithmetic check: lifetime_days from the cert dates, verdict against the §6.4 rules

Append the results to docs/ACCURACY_REPORT.md as section A3b. Any discrepancy is a bug in our scanner, not in the reference tool.

A2 — Contract amendment v1.1: resolve the two ambiguities Gate A found

The report correctly flagged both of these as contract gaps rather than papering over them. Resolutions:

sha1-intermediate.badssl.com — scope of CERT_WEAK_SIGNATURE. The finding applies to every certificate in the presented chain except the root. A SHA-1 intermediate is as fatal as a SHA-1 leaf. The root is exempt because it is self-signed and trusted by identity, so its own signature carries no security meaning. Update the §8 trigger wording, and set evidence.position to which certificate in the chain triggered it.

dh480.badssl.com — weak key exchange has no finding code. Add to §8:

Code	Module	Sev	Trigger
TLS_WEAK_KEY_EXCHANGE	tls	high	DHE parameters < 2048 bits, or ECDHE curve < 256 bits

Add key_exchange to tls.data: { "type": "ECDHE", "bits": 256, "curve": "X25519" }, nullable when not determinable.

Add both to docs/findings/ and to the frontend's finding docs route. Bump the §14 amendment log to v1.1.

A3 — Quarantine the network-dependent tests

The report documents 1–8 failures per run in badssl.com-backed tests, never the same set twice, always passing in isolation. The diagnosis — hammering a free unSLA'd demo server — is almost certainly right. But a suite that goes red at random is a suite people stop reading, and we are about to add a second developer's worth of AI sessions to this repo.

Split them: mark every test that touches an external network with a @pytest.mark.network marker, and exclude that marker from the default pytest run via pyproject.toml. They then run only in the accuracy harness, deliberately, when we want them.

The default suite must be deterministic and offline. It should pass on a plane.

A4 — Soften the WHOIS-derived domain expiry findings

Gate A surfaced example.com producing DOMAIN_EXPIRING_CRITICAL because the authoritative record genuinely says it expires in two days. The session's conclusion — report the record faithfully — is right in principle. But DOMAIN_EXPIRING_CRITICAL is a critical severity, and per §9 a single critical caps the whole result at F.

So a stale, redacted or oddly-formatted WHOIS record — common across .in, .co.in and privacy-protected domains, which is most of our market — can drop a perfectly healthy site to an F. That is the precise false-positive that destroys trust on first contact.

Three changes:

Demote DOMAIN_EXPIRING_CRITICAL from critical to high. Registration expiry is real and urgent, but it is not a TLS failure and should not force an F.
Attribute the source in the copy: "The registry record for {domain} says it expires on {date}. Confirm with your registrar — registry records are sometimes stale." Never phrase a WHOIS-derived claim in our own voice.
Exclude domain-expiry findings from the §9 grade caps entirely. They appear in the findings list at their stated severity, and they do not move the letter grade.

Update §8, §9 and the finding docs. Include in the v1.1 amendment.

A5 — Give TLS_WEAK_CIPHER real test coverage

rc4.badssl.com is a dead fixture — the report proved that properly with openssl -provider legacy. Good work, but the consequence is that TLS_WEAK_CIPHER now has zero positive test coverage: a shipped finding code that has never once fired in a test.

Add unit coverage at the classification-function level rather than the network level. Feed the cipher classifier a fixed list of known-weak suite names (RC4, 3DES, NULL, EXPORT, CBC-only) and known-good ones, and assert the classification. No server needed, deterministic, runs offline.

Do the same for TLS_WEAK_KEY_EXCHANGE once A2 adds it.
