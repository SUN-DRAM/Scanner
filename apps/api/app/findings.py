"""The finding catalogue (contract §8) — closed set, 42 codes.

Every entry is written for a founder who has never thought about certificate
lifetimes, not a security engineer: plain English, states what's wrong and
what to do about it, sentence case, active voice, no jargon left unexplained.

`build_finding(code, evidence)` is how scanner modules (Step 5) turn a raw
detection into a `schemas.Finding`. `evidence` must supply every key the
code's templates reference — `{hostname}` is expected on every one of them,
since it's the scan's own hostname, not part of any module's data payload.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.enums import ModuleName, Severity
from app.schemas import Finding

_DATE_EVIDENCE_KEYS = ("not_before", "not_after", "domain_created_at", "domain_expires_at")


@dataclass(frozen=True)
class FindingDefinition:
    code: str
    module: ModuleName
    severity: Severity
    title_template: str
    description_template: str
    remediation_template: str


_DEFINITIONS: tuple[FindingDefinition, ...] = (
    # --- certificate ---
    FindingDefinition(
        code="CERT_EXPIRED",
        module=ModuleName.CERTIFICATE,
        severity=Severity.CRITICAL,
        title_template="Certificate expired on {not_after_display}",
        description_template=(
            "The TLS certificate for {hostname} expired on {not_after_display}. Browsers and "
            "API clients will now refuse the connection outright, showing visitors a hard "
            "security warning instead of the site."
        ),
        remediation_template=(
            "Renew the certificate immediately and confirm the new one is actually being "
            "served — an expired certificate usually means the renewal automation already "
            "failed once before."
        ),
    ),
    FindingDefinition(
        code="CERT_NOT_YET_VALID",
        module=ModuleName.CERTIFICATE,
        severity=Severity.CRITICAL,
        title_template="Certificate is not valid until {not_before_display}",
        description_template=(
            "The TLS certificate for {hostname} has a start date of {not_before_display}, "
            "which is in the future. Until then, browsers will reject it the same way they "
            "reject an expired one."
        ),
        remediation_template=(
            "Check the server's clock and the certificate's issuance date — this is almost "
            "always a misconfigured system clock or a certificate issued for the wrong period."
        ),
    ),
    FindingDefinition(
        code="CERT_HOSTNAME_MISMATCH",
        module=ModuleName.CERTIFICATE,
        severity=Severity.CRITICAL,
        title_template="Certificate does not cover {hostname}",
        description_template=(
            "The certificate presented by {hostname} does not list it in the certificate's "
            "common name or subject alternative names. Browsers will show a name-mismatch "
            "warning to every visitor."
        ),
        remediation_template=(
            "Reissue the certificate with {hostname} included in its subject alternative "
            "names, or point this hostname at the correct certificate."
        ),
    ),
    FindingDefinition(
        code="CERT_SELF_SIGNED",
        module=ModuleName.CERTIFICATE,
        severity=Severity.CRITICAL,
        title_template="Certificate is self-signed",
        description_template=(
            "The certificate for {hostname} is signed by itself rather than by a certificate "
            "authority browsers trust. Every visitor will see a security warning before they "
            "can reach the site."
        ),
        remediation_template=(
            "Replace it with a certificate from a trusted certificate authority — Let's "
            "Encrypt is free and can be automated."
        ),
    ),
    FindingDefinition(
        code="CERT_EXPIRING_CRITICAL",
        module=ModuleName.CERTIFICATE,
        severity=Severity.CRITICAL,
        title_template="Certificate expires in {days_until_expiry} days",
        description_template=(
            "The certificate for {hostname} is valid until {not_after_display}. With "
            "{days_until_expiry} days left, there is no time left for a renewal to fail and "
            "be retried."
        ),
        remediation_template=(
            "Renew the certificate today. If renewal is automated, check that the automation "
            "actually ran — a warning this close to expiry usually means it did not."
        ),
    ),
    FindingDefinition(
        code="CERT_EXPIRING_SOON",
        module=ModuleName.CERTIFICATE,
        severity=Severity.HIGH,
        title_template="Certificate expires in {days_until_expiry} days",
        description_template=(
            "The certificate for {hostname} is valid until {not_after_display}. Renewal "
            "usually needs to happen before day 30 to leave room for failure."
        ),
        remediation_template=(
            "Set up automated renewal, or renew now and add an expiry alert at 30, 14 and 7 days."
        ),
    ),
    FindingDefinition(
        code="CERT_EXPIRING_WARN",
        module=ModuleName.CERTIFICATE,
        severity=Severity.MEDIUM,
        title_template="Certificate expires in {days_until_expiry} days",
        description_template=(
            "The certificate for {hostname} is valid until {not_after_display}. That's a "
            "comfortable window, but worth putting on a calendar now rather than trusting "
            "memory."
        ),
        remediation_template=(
            "Confirm renewal is automated. If it is not, book a specific day to renew it "
            "rather than waiting for a reminder."
        ),
    ),
    FindingDefinition(
        code="CERT_WEAK_KEY",
        module=ModuleName.CERTIFICATE,
        severity=Severity.HIGH,
        title_template="Certificate uses a weak {key_algorithm} key",
        description_template=(
            "The certificate for {hostname} uses a {key_algorithm} key of {key_size_bits} "
            "bits, below the minimum modern browsers and auditors expect (RSA 2048, ECDSA "
            "256)."
        ),
        remediation_template=(
            "Reissue the certificate with a stronger key — RSA 2048-bit or larger, or an "
            "ECDSA P-256 key."
        ),
    ),
    FindingDefinition(
        code="CERT_WEAK_SIGNATURE",
        module=ModuleName.CERTIFICATE,
        severity=Severity.HIGH,
        title_template="Certificate uses a weak {signature_algorithm} signature",
        description_template=(
            "Certificate #{position} in {hostname}'s chain is signed with "
            "{signature_algorithm}, an algorithm no longer considered safe against forgery. "
            "This applies to any certificate in the chain except the self-signed root, whose "
            "own signature carries no security meaning — a weak intermediate is as fatal as a "
            "weak leaf."
        ),
        remediation_template=(
            "Reissue the certificate with a SHA-256 or stronger signature algorithm — most "
            "modern certificate authorities do this by default. If the affected certificate is "
            "an intermediate, this is the certificate authority's problem to fix, not the "
            "server operator's — contact them for an updated chain."
        ),
    ),
    FindingDefinition(
        code="CERT_LONG_LIFETIME",
        module=ModuleName.CERTIFICATE,
        severity=Severity.MEDIUM,
        title_template="Certificate lifetime is {lifetime_days} days",
        description_template=(
            "The certificate for {hostname} was issued for {lifetime_days} days. From 15 "
            "March 2026 the CA/Browser Forum caps new certificates at 200 days, and from 15 "
            "March 2027 at 100 days — a lifetime this long will not be issuable much longer."
        ),
        remediation_template=(
            "Move to a certificate authority and renewal process built for short lifetimes, "
            "such as an automated ACME client with Let's Encrypt or ZeroSSL."
        ),
    ),
    FindingDefinition(
        code="CERT_NO_OCSP_STAPLING",
        module=ModuleName.CERTIFICATE,
        severity=Severity.LOW,
        title_template="OCSP stapling is not enabled",
        description_template=(
            "{hostname} does not staple an OCSP response during the TLS handshake. Some "
            "browsers then check revocation status separately, adding a small delay and a "
            "privacy leak of which sites a visitor checks."
        ),
        remediation_template=(
            "Enable OCSP stapling in the web server's TLS configuration — most modern "
            "servers support it with a single directive."
        ),
    ),
    # --- chain ---
    FindingDefinition(
        code="CHAIN_INCOMPLETE",
        module=ModuleName.CHAIN,
        severity=Severity.HIGH,
        title_template="Certificate chain is missing intermediates",
        description_template=(
            "{hostname} does not present the full chain of intermediate certificates up to a "
            "trusted root. Some browsers and most non-browser clients (curl, mobile apps, "
            "payment SDKs) will fail to validate the connection even though desktop browsers "
            "may appear fine."
        ),
        remediation_template=(
            "Configure the server to serve the full intermediate chain — the certificate "
            "authority's site has the correct bundle for this certificate."
        ),
    ),
    FindingDefinition(
        code="CHAIN_OUT_OF_ORDER",
        module=ModuleName.CHAIN,
        severity=Severity.MEDIUM,
        title_template="Certificate chain is presented out of order",
        description_template=(
            "{hostname} sends its certificates in the wrong order. Some clients tolerate "
            "this; strict ones (notably many mobile and IoT TLS libraries) will fail to "
            "build a valid chain."
        ),
        remediation_template=(
            "Reorder the certificate bundle so the leaf certificate comes first, followed by "
            "intermediates, ending with (or just before) the root."
        ),
    ),
    FindingDefinition(
        code="CHAIN_UNTRUSTED_ROOT",
        module=ModuleName.CHAIN,
        severity=Severity.CRITICAL,
        title_template="Certificate chain ends in an untrusted root",
        description_template=(
            "The root certificate at the top of {hostname}'s chain is not in the standard "
            "trust stores browsers and operating systems ship with. Visitors will see a "
            "security warning."
        ),
        remediation_template=(
            "Reissue the certificate from a certificate authority whose root is trusted by "
            "major browsers and operating systems."
        ),
    ),
    FindingDefinition(
        code="CHAIN_INTERMEDIATE_EXPIRING",
        module=ModuleName.CHAIN,
        severity=Severity.HIGH,
        title_template="An intermediate certificate expires in {days_until_expiry} days",
        description_template=(
            "One of the intermediate certificates in {hostname}'s chain ({intermediate_subject}"
            ") expires on {not_after_display}. When it expires, the whole chain breaks even "
            "if the leaf certificate is still valid."
        ),
        remediation_template=(
            "Contact the certificate authority for an updated intermediate bundle, or "
            "reissue the leaf certificate so a current intermediate is served."
        ),
    ),
    # --- tls ---
    FindingDefinition(
        code="TLS_LEGACY_PROTOCOL",
        module=ModuleName.TLS,
        severity=Severity.HIGH,
        title_template="Legacy TLS protocol {protocol} is enabled",
        description_template=(
            "{hostname} still accepts connections over {protocol}, which browsers have "
            "removed support for and which has known weaknesses."
        ),
        remediation_template=(
            "Disable TLS 1.0 and TLS 1.1 in the server's TLS configuration, keeping TLS 1.2 "
            "and TLS 1.3 only."
        ),
    ),
    FindingDefinition(
        code="TLS_NO_TLS13",
        module=ModuleName.TLS,
        severity=Severity.LOW,
        title_template="TLS 1.3 is not supported",
        description_template=(
            "{hostname} does not negotiate TLS 1.3, the current standard that is faster and "
            "more secure than TLS 1.2."
        ),
        remediation_template=(
            "Enable TLS 1.3 in the server's TLS configuration — most modern web servers "
            "support it with no other changes needed."
        ),
    ),
    FindingDefinition(
        code="TLS_WEAK_CIPHER",
        module=ModuleName.TLS,
        severity=Severity.HIGH,
        title_template="Weak cipher suites are enabled",
        description_template=(
            "{hostname} accepts weak cipher suites ({weak_ciphers}), which can be broken or "
            "downgraded by an attacker on the network path."
        ),
        remediation_template=(
            "Remove RC4, 3DES, NULL, EXPORT and CBC-only cipher suites from the server's TLS "
            "configuration, keeping modern AEAD suites only."
        ),
    ),
    FindingDefinition(
        code="TLS_WEAK_KEY_EXCHANGE",
        module=ModuleName.TLS,
        severity=Severity.HIGH,
        title_template="Key exchange uses weak {key_exchange_type} parameters",
        description_template=(
            "{hostname} negotiated {key_exchange_type} key exchange with only "
            "{key_exchange_bits} bits, below the minimum modern clients expect (DHE 2048 "
            "bits, ECDHE 256-bit curve). A weak key exchange narrows the effort needed to "
            "break forward secrecy for this session."
        ),
        remediation_template=(
            "Configure the server to offer only DHE groups of 2048 bits or larger, or ECDHE "
            "curves of 256 bits or larger (X25519 or P-256) — most modern web servers default "
            "to safe groups already, so this usually means removing an explicit legacy "
            "override."
        ),
    ),
    FindingDefinition(
        code="TLS_NO_FORWARD_SECRECY",
        module=ModuleName.TLS,
        severity=Severity.MEDIUM,
        title_template="Connection does not use forward secrecy",
        description_template=(
            "{hostname} negotiated {cipher}, which does not provide forward secrecy. If the "
            "server's private key is ever exposed, past recorded traffic could be decrypted."
        ),
        remediation_template=(
            "Prioritise ECDHE or DHE cipher suites in the server's TLS configuration so "
            "every session gets a unique key."
        ),
    ),
    # --- dns ---
    FindingDefinition(
        code="DNS_NO_CAA",
        module=ModuleName.DNS,
        severity=Severity.LOW,
        title_template="No CAA record found",
        description_template=(
            "{hostname} has no CAA (Certification Authority Authorization) record, so any "
            "certificate authority is allowed to issue certificates for it."
        ),
        remediation_template=(
            "Add a CAA record naming the certificate authority you actually use, for "
            'example: 0 issue "letsencrypt.org".'
        ),
    ),
    FindingDefinition(
        code="DNS_NO_DNSSEC",
        module=ModuleName.DNS,
        severity=Severity.INFO,
        title_template="DNSSEC is not enabled",
        description_template=(
            "{hostname} does not sign its DNS records with DNSSEC, so a network attacker "
            "could forge DNS responses for it without detection."
        ),
        remediation_template=(
            "Enable DNSSEC signing with your DNS provider — most managed DNS providers "
            "support turning it on directly in their dashboard."
        ),
    ),
    FindingDefinition(
        code="DOMAIN_EXPIRING_CRITICAL",
        module=ModuleName.DNS,
        # Gate A follow-up A4: demoted from critical to high. Registration
        # expiry is real and urgent, but it's not a TLS failure — a stale or
        # oddly-formatted WHOIS record (common on .in/.co.in and
        # privacy-protected domains, most of this product's market) must
        # never be able to cap a healthy site's grade at F on its own. Also
        # excluded from the §9 grade-cap overrides entirely — see
        # grading.py's GRADE_CAP_EXCLUDED_CODES.
        severity=Severity.HIGH,
        title_template="Domain registration expires in {days_until_domain_expiry} days",
        description_template=(
            "The registry record for {hostname} says it expires on "
            "{domain_expires_at_display}. If that's accurate and it lapses, the domain — and "
            "every certificate and email address tied to it — stops working entirely. Confirm "
            "with your registrar before treating this as certain: registry records are "
            "sometimes stale or inconsistently formatted, especially for privacy-protected "
            "domains."
        ),
        remediation_template=(
            "Confirm the actual expiry with your registrar. If it's accurate, renew the "
            "domain registration today and turn on auto-renewal so this cannot happen "
            "silently again."
        ),
    ),
    FindingDefinition(
        code="DOMAIN_EXPIRING_SOON",
        module=ModuleName.DNS,
        severity=Severity.HIGH,
        title_template="Domain registration expires in {days_until_domain_expiry} days",
        description_template=(
            "The registry record for {hostname} says it expires on "
            "{domain_expires_at_display} with registrar {registrar}. Registry records are "
            "sometimes stale — confirm the actual date with the registrar directly."
        ),
        remediation_template=(
            "Confirm the actual expiry with your registrar, then renew the domain "
            "registration and turn on auto-renewal so this does not need tracking manually."
        ),
    ),
    FindingDefinition(
        code="DNS_SINGLE_NAMESERVER",
        module=ModuleName.DNS,
        severity=Severity.MEDIUM,
        title_template="Only one nameserver is configured",
        description_template=(
            "{hostname} has a single authoritative nameserver. If it becomes unreachable, "
            "the domain stops resolving for everyone."
        ),
        remediation_template=(
            "Add at least one more nameserver, ideally from a different provider or "
            "network, for redundancy."
        ),
    ),
    # --- email_auth ---
    FindingDefinition(
        code="SPF_MISSING",
        module=ModuleName.EMAIL_AUTH,
        severity=Severity.MEDIUM,
        title_template="No SPF record found",
        description_template=(
            "{hostname} has no SPF record, so receiving mail servers have no way to know "
            "which servers are allowed to send email as this domain. That makes it easier "
            "to spoof and more likely to land in spam."
        ),
        remediation_template=(
            "Publish an SPF TXT record listing the mail services you actually use to send "
            "email, for example: v=spf1 include:_spf.google.com ~all."
        ),
    ),
    FindingDefinition(
        code="SPF_WEAK_POLICY",
        module=ModuleName.EMAIL_AUTH,
        severity=Severity.LOW,
        title_template="SPF policy is too permissive",
        description_template=(
            "{hostname}'s SPF record ends in {policy}, which tells receiving mail servers to "
            "accept mail even when the sending server is not listed."
        ),
        remediation_template=(
            "Change the SPF record to end in ~all (soft fail) or -all (hard fail) once "
            "you're confident the listed senders are complete."
        ),
    ),
    FindingDefinition(
        code="SPF_TOO_MANY_LOOKUPS",
        module=ModuleName.EMAIL_AUTH,
        severity=Severity.MEDIUM,
        title_template="SPF record needs {lookup_count} DNS lookups",
        description_template=(
            "{hostname}'s SPF record requires {lookup_count} DNS lookups to evaluate, over "
            "the limit of 10 that the SPF standard allows. Mail servers may treat the whole "
            "record as a permanent failure once over the limit."
        ),
        remediation_template=(
            "Flatten or trim the SPF record — combine included services or remove ones no "
            "longer used to bring the lookup count under 10."
        ),
    ),
    FindingDefinition(
        code="DMARC_MISSING",
        module=ModuleName.EMAIL_AUTH,
        severity=Severity.MEDIUM,
        title_template="No DMARC record found",
        description_template=(
            "{hostname} has no DMARC record, so there is no policy telling mail servers what "
            "to do with email that fails SPF or DKIM checks, and no reporting on spoofing "
            "attempts."
        ),
        remediation_template=(
            "Publish a DMARC TXT record at _dmarc.{hostname}, starting with p=none to "
            "monitor before enforcing."
        ),
    ),
    FindingDefinition(
        code="DMARC_POLICY_NONE",
        module=ModuleName.EMAIL_AUTH,
        severity=Severity.LOW,
        title_template="DMARC policy is set to monitor only",
        description_template=(
            "{hostname}'s DMARC policy is p=none, which only requests reports and does not "
            "tell mail servers to reject or quarantine spoofed email."
        ),
        remediation_template=(
            "Once DMARC reports show legitimate mail is passing, move the policy to "
            "p=quarantine and then p=reject."
        ),
    ),
    FindingDefinition(
        code="DKIM_NOT_FOUND",
        module=ModuleName.EMAIL_AUTH,
        severity=Severity.INFO,
        title_template="No DKIM selector responded",
        description_template=(
            "None of the common DKIM selectors checked for {hostname} returned a key. This "
            "is a best-effort check — a real selector using an uncommon name would not be "
            "found this way."
        ),
        remediation_template=(
            "Confirm your email provider has DKIM signing enabled and note the selector "
            "name it uses, so it can be checked directly."
        ),
    ),
    # --- headers ---
    FindingDefinition(
        code="HSTS_MISSING",
        module=ModuleName.HEADERS,
        severity=Severity.HIGH,
        title_template="Strict-Transport-Security header is missing",
        description_template=(
            "{hostname} does not send an HSTS header, so browsers will trust plain HTTP for "
            "it until they are told otherwise, leaving an opening for downgrade attacks."
        ),
        remediation_template=(
            "Add a Strict-Transport-Security header once HTTPS is confirmed working "
            "everywhere, for example: max-age=31536000; includeSubDomains."
        ),
    ),
    FindingDefinition(
        code="HSTS_SHORT_MAX_AGE",
        module=ModuleName.HEADERS,
        severity=Severity.MEDIUM,
        title_template="HSTS max-age is short ({max_age_seconds} seconds)",
        description_template=(
            "{hostname}'s HSTS header only lasts {max_age_seconds} seconds, well under the "
            "recommended 180 days (15552000 seconds)."
        ),
        remediation_template=(
            "Increase the HSTS max-age to at least 15552000 seconds (180 days) once HTTPS "
            "is confirmed working everywhere."
        ),
    ),
    FindingDefinition(
        code="NO_HTTPS_REDIRECT",
        module=ModuleName.HEADERS,
        severity=Severity.HIGH,
        title_template="HTTP does not redirect to HTTPS",
        description_template=(
            "Visiting {hostname} over plain HTTP does not redirect to HTTPS, so anyone who "
            "types the address without https:// stays on an unencrypted connection."
        ),
        remediation_template=(
            "Add a server-level redirect from HTTP to HTTPS so no visitor is ever served the "
            "site unencrypted."
        ),
    ),
    FindingDefinition(
        code="CSP_MISSING",
        module=ModuleName.HEADERS,
        severity=Severity.MEDIUM,
        title_template="Content-Security-Policy header is missing",
        description_template=(
            "{hostname} does not send a Content-Security-Policy header, so the browser has "
            "no restriction on which scripts, styles or frames the page can load — a common "
            "way cross-site scripting turns into real damage."
        ),
        remediation_template=(
            "Start with a reporting-only Content-Security-Policy to see what the site "
            "actually loads, then move to an enforcing policy."
        ),
    ),
    FindingDefinition(
        code="XFO_MISSING",
        module=ModuleName.HEADERS,
        severity=Severity.LOW,
        title_template="X-Frame-Options header is missing",
        description_template=(
            "{hostname} does not send X-Frame-Options and its Content-Security-Policy (if "
            "any) has no frame-ancestors directive, so the page can be embedded in another "
            "site's frame — the basis of clickjacking attacks."
        ),
        remediation_template=(
            "Add X-Frame-Options: DENY (or SAMEORIGIN if framing by your own pages is "
            "needed), or a CSP frame-ancestors directive."
        ),
    ),
    FindingDefinition(
        code="XCTO_MISSING",
        module=ModuleName.HEADERS,
        severity=Severity.LOW,
        title_template="X-Content-Type-Options header is missing",
        description_template=(
            "{hostname} does not send X-Content-Type-Options: nosniff, so older browsers "
            "may try to guess a file's type rather than trusting the declared one, which has "
            "been used to smuggle scripts past filters."
        ),
        remediation_template="Add X-Content-Type-Options: nosniff to every response.",
    ),
    FindingDefinition(
        code="REFERRER_POLICY_MISSING",
        module=ModuleName.HEADERS,
        severity=Severity.LOW,
        title_template="Referrer-Policy header is missing",
        description_template=(
            "{hostname} does not send a Referrer-Policy header, so the browser's default "
            "behaviour decides how much of this site's URLs leak to other sites when "
            "visitors click outbound links."
        ),
        remediation_template=(
            "Add a Referrer-Policy header, for example: strict-origin-when-cross-origin."
        ),
    ),
    FindingDefinition(
        code="PERMISSIONS_POLICY_MISSING",
        module=ModuleName.HEADERS,
        severity=Severity.INFO,
        title_template="Permissions-Policy header is missing",
        description_template=(
            "{hostname} does not send a Permissions-Policy header, so there is no explicit "
            "limit on which browser features (camera, microphone, geolocation) embedded "
            "content is allowed to request."
        ),
        remediation_template=(
            "Add a Permissions-Policy header that turns off features the site does not use."
        ),
    ),
    FindingDefinition(
        code="SERVER_VERSION_DISCLOSED",
        module=ModuleName.HEADERS,
        severity=Severity.LOW,
        title_template="Server header discloses a version number",
        description_template=(
            '{hostname} sends a Server header of "{server_header}", which tells an attacker '
            "exactly which software version to look for known vulnerabilities in."
        ),
        remediation_template=(
            "Configure the web server to omit its version number from the Server header, or "
            "remove the header entirely."
        ),
    ),
    # --- readiness ---
    FindingDefinition(
        code="READINESS_MANUAL_2027",
        module=ModuleName.READINESS,
        severity=Severity.HIGH,
        title_template="This certificate needs a manual renewal process",
        description_template=(
            "{hostname}'s certificate has a {current_lifetime_days}-day lifetime, "
            "consistent with a manual renewal process. {verdict_reason}"
        ),
        remediation_template=(
            "Move to an automated ACME client (Let's Encrypt, ZeroSSL, Google Trust "
            "Services or Buypass) before 15 March 2027, when 100-day maximum lifetimes make "
            "manual renewal impractical at any scale."
        ),
    ),
    FindingDefinition(
        code="READINESS_UNVERIFIED",
        module=ModuleName.READINESS,
        severity=Severity.MEDIUM,
        title_template="Renewal automation could not be confirmed",
        description_template=(
            "{hostname}'s certificate has a short enough lifetime to suggest automation, "
            "but it is not from a certificate authority this scan recognises as an ACME "
            "provider. {verdict_reason}"
        ),
        remediation_template=(
            "Confirm renewal is actually automated. If it is, no action is needed — this "
            "finding just means the scan could not verify it from the issuer name alone."
        ),
    ),
    FindingDefinition(
        code="READINESS_OK",
        module=ModuleName.READINESS,
        severity=Severity.INFO,
        title_template="Certificate renewal looks automated",
        description_template=(
            "{hostname}'s certificate has a {current_lifetime_days}-day lifetime from a "
            "recognised automated issuer. {verdict_reason}"
        ),
        remediation_template=(
            "No action needed. Keep the renewal automation monitored so a silent failure "
            "does not go unnoticed."
        ),
    ),
)

FINDINGS_BY_CODE: dict[str, FindingDefinition] = {d.code: d for d in _DEFINITIONS}

if len(FINDINGS_BY_CODE) != len(_DEFINITIONS):
    raise RuntimeError("Duplicate finding code in the catalogue — codes must be unique.")


def docs_path_for(code: str) -> str:
    return "/docs/findings/" + code.lower().replace("_", "-")


def _format_date_display(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _derived_display_fields(evidence: Mapping[str, Any]) -> dict[str, str]:
    derived: dict[str, str] = {}
    for key in _DATE_EVIDENCE_KEYS:
        value = evidence.get(key)
        if isinstance(value, str):
            with contextlib.suppress(ValueError):
                derived[f"{key}_display"] = _format_date_display(value)
    return derived


def build_finding(
    code: str, evidence: Mapping[str, Any], *, severity: Severity | None = None
) -> Finding:
    """Renders a `schemas.Finding` from the catalogue entry for `code`.

    `evidence` must include every key its templates reference — see the
    `{...}` placeholders in the `FindingDefinition` above. Raises `ValueError`
    with the missing key named, rather than silently emitting broken copy.
    """
    try:
        definition = FINDINGS_BY_CODE[code]
    except KeyError as exc:
        raise ValueError(f"'{code}' is not a known finding code.") from exc

    context: dict[str, Any] = {**evidence, **_derived_display_fields(evidence)}
    try:
        title = definition.title_template.format(**context)
        description = definition.description_template.format(**context)
        remediation = definition.remediation_template.format(**context)
    except KeyError as exc:
        raise ValueError(
            f"Finding {code} is missing evidence key {exc} required by its template."
        ) from exc

    return Finding(
        code=code,
        module=definition.module,
        severity=severity if severity is not None else definition.severity,
        title=title,
        description=description,
        remediation=remediation,
        evidence=dict(evidence),
        docs_path=docs_path_for(code),
    )
