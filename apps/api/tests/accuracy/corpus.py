"""Fixed domain corpus for the Gate A accuracy harness (`run.py`).

Not part of the normal `pytest` run — every host here needs live network
access to a real, external server. Run via `python -m tests.accuracy.run`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownBadHost:
    hostname: str
    # The finding code we're confident this host's known defect should
    # trigger. `None` means: no confident a-priori expectation (the
    # contract's finding catalogue may not have explicit coverage for this
    # specific defect) — observe and report the actual result honestly
    # rather than asserting a guess.
    expected_code: str | None
    note: str


# Every host here is a well-known badssl.com fixture for one specific,
# documented TLS defect. `expected_code` is asserted when set; every host
# is asserted not to crash regardless.
KNOWN_BAD_HOSTS: tuple[KnownBadHost, ...] = (
    KnownBadHost("expired.badssl.com", "CERT_EXPIRED", "certificate past not_after"),
    KnownBadHost("self-signed.badssl.com", "CERT_SELF_SIGNED", "issuer == subject"),
    KnownBadHost("wrong.host.badssl.com", "CERT_HOSTNAME_MISMATCH", "cert doesn't cover hostname"),
    KnownBadHost("untrusted-root.badssl.com", "CHAIN_UNTRUSTED_ROOT", "root not in trust store"),
    KnownBadHost("incomplete-chain.badssl.com", "CHAIN_INCOMPLETE", "intermediates missing"),
    KnownBadHost(
        "sha1-intermediate.badssl.com",
        None,
        "SHA-1 signature on an INTERMEDIATE, not the leaf — certificate.py only "
        "inspects the leaf's signature_algorithm; contract §8's CERT_WEAK_SIGNATURE "
        "wording doesn't specify leaf-only vs chain-wide, so this is a real "
        "coverage question, not a confident expectation either way.",
    ),
    KnownBadHost(
        "rc4.badssl.com",
        None,
        "named for RC4, but confirmed dead as of Gate A (2026-08-11): raw `openssl s_client "
        "-cipher ALL:@SECLEVEL=0 -provider legacy -provider default` against it still gets "
        "SSL_ALERT_HANDSHAKE_FAILURE — the server itself no longer negotiates anything, RC4 "
        "included, for any client. Our scanner's status=error is the honest reflection of that, "
        "not a coverage gap; badssl.com's own test fixture has bit-rotted, not our probe.",
    ),
    KnownBadHost(
        "dh480.badssl.com",
        None,
        "480-bit DHE key exchange — contract §8's TLS_WEAK_CIPHER trigger list is "
        "'RC4, 3DES, NULL, EXPORT, or CBC-only suites' only; weak DHE *key size* "
        "isn't an enumerated trigger for any contract finding, so zero findings "
        "here may be correct, not a bug. Flagged for human review either way.",
    ),
    KnownBadHost("tls-v1-0.badssl.com", "TLS_LEGACY_PROTOCOL", "TLS 1.0 only"),
    KnownBadHost(
        "no-subject.badssl.com",
        None,
        "certificate has no subject field — robustness/parsing edge case, not a "
        "specific contract finding; must not crash certificate.py's subject "
        "extraction",
    ),
    KnownBadHost(
        "1000-sans.badssl.com",
        None,
        "certificate with 1000 SANs — parsing/size stress case, not a defect the "
        "catalogue targets; must not crash or time out",
    ),
    KnownBadHost(
        "no-common-name.badssl.com",
        None,
        "certificate has no CN — robustness/parsing edge case for "
        "subject_common_name extraction, not a specific contract finding",
    ),
)

# "Known good" as in "reputable, real, not a defect fixture" — it does NOT
# mean every one of these is actually clean. Gate A cross-checked google.com
# (TLS_LEGACY_PROTOCOL, HSTS_MISSING, NO_HTTPS_REDIRECT) and cloudflare.com
# (TLS_LEGACY_PROTOCOL) directly with `openssl s_client -tls1`/`curl -I` and
# confirmed both findings are real: Google's and Cloudflare's edges still
# negotiate TLS 1.0 for compatibility, and google.com's apex neither sets
# HSTS nor redirects its bare HTTP listener to HTTPS. razorpay.com's
# READINESS_MANUAL_2027 is similarly real (cert lifetime > 100 days). A
# failure below is the harness correctly reporting scanner accuracy, not a
# scanner bug — read the accompanying finding list before assuming otherwise.
KNOWN_GOOD_HOSTS: tuple[str, ...] = (
    "google.com",
    "cloudflare.com",
    "github.com",
    "letsencrypt.org",
    "razorpay.com",
    "zerodha.com",
)

# No assertions — print full results for human review. Messy real-world
# Indian production setups, exactly what this product's actual buyers run.
INDIAN_REAL_WORLD_HOSTS: tuple[str, ...] = (
    "irctc.co.in",
    "sbi.co.in",
    "incometax.gov.in",
    "uidai.gov.in",
    "flipkart.com",
    "swiggy.com",
    "iitb.ac.in",
    "iitd.ac.in",
    "du.ac.in",
)


@dataclass(frozen=True)
class EdgeCase:
    label: str
    hostname: str
    note: str


EDGE_CASES: tuple[EdgeCase, ...] = (
    EdgeCase(
        "nonexistent_domain",
        "this-domain-should-not-exist-sundram-gate-a.invalid",
        "must fail fast via HostnameResolutionError, never hang or crash",
    ),
    EdgeCase(
        "resolves_but_refuses_443",
        "aspmx.l.google.com",
        "a real, live Gmail MX host — resolves via DNS but doesn't serve HTTPS "
        "on 443; every module depending on the TLS handshake should degrade to "
        "status=error cleanly, not crash the whole scan",
    ),
    EdgeCase(
        "no_mx_records",
        "example.com",
        "IANA's reserved example domain — deliberately minimal DNS, no mail setup",
    ),
    EdgeCase(
        "no_caa_record",
        "example.com",
        "same minimal-DNS domain — also almost certainly has no CAA record",
    ),
    EdgeCase(
        "idn_domain",
        "münchen.de",
        "the City of Munich's real site — genuine IDN, needs punycode "
        "(xn--mnchen-3ya.de) normalisation end to end",
    ),
    EdgeCase(
        "cloudflare_proxied",
        "canva.com",
        "well-known Cloudflare-proxied site — the presented cert is Cloudflare's, "
        "not Canva's own origin cert; note this can change over time so this is "
        "observational, not a hard assertion",
    ),
    EdgeCase(
        "wildcard_certificate",
        "github.io",
        "GitHub Pages' own apex — many *.github.io sites present a wildcard cert; "
        "observational, checks is_wildcard rather than assuming a specific result",
    ),
    EdgeCase(
        "whois_privacy_redacted",
        "razorpay.com",
        "typical corporate domain likely running WHOIS privacy — checks the dns "
        "module returns clean nulls rather than a wrong or fabricated date on "
        "any WHOIS failure/redaction, per contract §7 rule 7",
    ),
)
