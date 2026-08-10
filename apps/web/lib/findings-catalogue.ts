/**
 * The 42 finding codes from contract §8 — code, module and default
 * severity only, exactly as that table lists them. This mirrors the
 * *shape* of `apps/api/app/findings.py`'s catalogue so `generateStaticParams`
 * can pre-render every `/docs/findings/[code]` route; it is not a second
 * source of truth for grading (severities here are the contract's fixed
 * defaults for display only — the actual `Finding.severity` on a scan
 * result always comes from the API).
 */

import type { ModuleName, Severity } from "@/types/contract";

export interface FindingCatalogueEntry {
  code: string;
  module: ModuleName;
  severity: Severity;
}

export const FINDINGS_CATALOGUE: readonly FindingCatalogueEntry[] = [
  { code: "CERT_EXPIRED", module: "certificate", severity: "critical" },
  { code: "CERT_NOT_YET_VALID", module: "certificate", severity: "critical" },
  { code: "CERT_HOSTNAME_MISMATCH", module: "certificate", severity: "critical" },
  { code: "CERT_SELF_SIGNED", module: "certificate", severity: "critical" },
  { code: "CERT_EXPIRING_CRITICAL", module: "certificate", severity: "critical" },
  { code: "CERT_EXPIRING_SOON", module: "certificate", severity: "high" },
  { code: "CERT_EXPIRING_WARN", module: "certificate", severity: "medium" },
  { code: "CERT_WEAK_KEY", module: "certificate", severity: "high" },
  { code: "CERT_WEAK_SIGNATURE", module: "certificate", severity: "high" },
  { code: "CERT_LONG_LIFETIME", module: "certificate", severity: "medium" },
  { code: "CERT_NO_OCSP_STAPLING", module: "certificate", severity: "low" },
  { code: "CHAIN_INCOMPLETE", module: "chain", severity: "high" },
  { code: "CHAIN_OUT_OF_ORDER", module: "chain", severity: "medium" },
  { code: "CHAIN_UNTRUSTED_ROOT", module: "chain", severity: "critical" },
  { code: "CHAIN_INTERMEDIATE_EXPIRING", module: "chain", severity: "high" },
  { code: "TLS_LEGACY_PROTOCOL", module: "tls", severity: "high" },
  { code: "TLS_NO_TLS13", module: "tls", severity: "low" },
  { code: "TLS_WEAK_CIPHER", module: "tls", severity: "high" },
  { code: "TLS_NO_FORWARD_SECRECY", module: "tls", severity: "medium" },
  { code: "DNS_NO_CAA", module: "dns", severity: "low" },
  { code: "DNS_NO_DNSSEC", module: "dns", severity: "info" },
  { code: "DOMAIN_EXPIRING_CRITICAL", module: "dns", severity: "critical" },
  { code: "DOMAIN_EXPIRING_SOON", module: "dns", severity: "high" },
  { code: "DNS_SINGLE_NAMESERVER", module: "dns", severity: "medium" },
  { code: "SPF_MISSING", module: "email_auth", severity: "medium" },
  { code: "SPF_WEAK_POLICY", module: "email_auth", severity: "low" },
  { code: "SPF_TOO_MANY_LOOKUPS", module: "email_auth", severity: "medium" },
  { code: "DMARC_MISSING", module: "email_auth", severity: "medium" },
  { code: "DMARC_POLICY_NONE", module: "email_auth", severity: "low" },
  { code: "DKIM_NOT_FOUND", module: "email_auth", severity: "info" },
  { code: "HSTS_MISSING", module: "headers", severity: "high" },
  { code: "HSTS_SHORT_MAX_AGE", module: "headers", severity: "medium" },
  { code: "NO_HTTPS_REDIRECT", module: "headers", severity: "high" },
  { code: "CSP_MISSING", module: "headers", severity: "medium" },
  { code: "XFO_MISSING", module: "headers", severity: "low" },
  { code: "XCTO_MISSING", module: "headers", severity: "low" },
  { code: "REFERRER_POLICY_MISSING", module: "headers", severity: "low" },
  { code: "PERMISSIONS_POLICY_MISSING", module: "headers", severity: "info" },
  { code: "SERVER_VERSION_DISCLOSED", module: "headers", severity: "low" },
  { code: "READINESS_MANUAL_2027", module: "readiness", severity: "high" },
  { code: "READINESS_UNVERIFIED", module: "readiness", severity: "medium" },
  { code: "READINESS_OK", module: "readiness", severity: "info" },
] as const;

/** Contract §6.3: `docs_path` is `/docs/findings/` + the code lowercased
 * with underscores turned into hyphens. */
export function codeToSlug(code: string): string {
  return code.toLowerCase().replaceAll("_", "-");
}

export function slugToCode(slug: string): string | null {
  const normalized = slug.toUpperCase().replaceAll("-", "_");
  const match = FINDINGS_CATALOGUE.find((entry) => entry.code === normalized);
  return match ? match.code : null;
}
