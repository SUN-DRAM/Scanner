/**
 * Hand-written mirror of apps/api/app/enums.py, apps/api/app/errors.py and
 * apps/api/app/schemas.py. Field names are identical, snake_case, no
 * conversion layer. Edit this file and the Python source together — see
 * CLAUDE.md rule 4.
 */

// --- enums (contract §5) ---

export type ScanStatus = "queued" | "running" | "completed" | "failed";

export type ModuleStatus = "ok" | "warn" | "fail" | "error" | "skipped";

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export type Grade = "A+" | "A" | "B" | "C" | "D" | "E" | "F";

export type ModuleName =
  | "certificate"
  | "chain"
  | "tls"
  | "dns"
  | "email_auth"
  | "headers"
  | "readiness";

export type ReadinessVerdict = "automated" | "semi_automated" | "manual" | "unknown";

export type LifetimePhase = "pre_2026" | "phase_200" | "phase_100" | "phase_47";

export type SpfPolicy = "none" | "neutral" | "softfail" | "fail" | "absent";

export type DmarcPolicy = "none" | "quarantine" | "reject" | "absent";

// --- error envelope (contract §7.4) ---

export type ErrorCode =
  | "VALIDATION_ERROR"
  | "INVALID_HOSTNAME"
  | "BLOCKED_TARGET"
  | "RATE_LIMITED"
  | "SCAN_NOT_FOUND"
  | "SCAN_FAILED"
  | "UPSTREAM_TIMEOUT"
  | "INTERNAL_ERROR";

export interface ApiError {
  code: ErrorCode;
  message: string;
  details: Record<string, unknown> | null;
  request_id: string;
}

export interface ErrorEnvelope {
  error: ApiError;
}

// --- 6.4 module data payloads ---

export interface CertificateData {
  subject_common_name: string;
  subject_alternative_names: string[];
  issuer_common_name: string;
  issuer_organization: string;
  serial_number: string;
  fingerprint_sha256: string;
  not_before: string;
  not_after: string;
  lifetime_days: number;
  days_until_expiry: number;
  is_expired: boolean;
  is_not_yet_valid: boolean;
  is_self_signed: boolean;
  is_wildcard: boolean;
  hostname_matches: boolean;
  key_algorithm: string;
  key_size_bits: number;
  signature_algorithm: string;
  ocsp_stapling: boolean;
  sct_count: number;
}

export type ChainCertificateRole = "leaf" | "intermediate" | "root";

export interface ChainCertificate {
  position: number;
  role: ChainCertificateRole;
  subject: string;
  issuer: string;
  not_after: string;
}

export interface ChainData {
  chain_length: number;
  is_complete: boolean;
  order_valid: boolean;
  trusted_root: string | null;
  certificates: ChainCertificate[];
}

export interface ProtocolSupport {
  supported: boolean;
  deprecated: boolean;
}

export interface TlsProtocols {
  tls1_0: ProtocolSupport;
  tls1_1: ProtocolSupport;
  tls1_2: ProtocolSupport;
  tls1_3: ProtocolSupport;
}

export interface TlsData {
  protocols: TlsProtocols;
  negotiated_protocol: string;
  negotiated_cipher: string;
  weak_ciphers: string[];
  forward_secrecy: boolean;
  supports_renegotiation: boolean;
}

export interface MxRecord {
  priority: number;
  host: string;
}

export interface DnsData {
  a_records: string[];
  aaaa_records: string[];
  cname: string | null;
  nameservers: string[];
  mx_records: MxRecord[];
  caa_records: string[];
  caa_present: boolean;
  dnssec_enabled: boolean;
  registrar: string | null;
  domain_created_at: string | null;
  domain_expires_at: string | null;
  days_until_domain_expiry: number | null;
}

export interface SpfData {
  present: boolean;
  record: string | null;
  policy: SpfPolicy;
  lookup_count: number;
  issues: string[];
}

export interface DmarcData {
  present: boolean;
  record: string | null;
  policy: DmarcPolicy;
  pct: number;
  rua_present: boolean;
}

export interface DkimData {
  selectors_checked: string[];
  selectors_found: string[];
}

export interface EmailAuthData {
  spf: SpfData;
  dmarc: DmarcData;
  dkim: DkimData;
}

export interface HstsData {
  present: boolean;
  max_age_seconds: number | null;
  include_subdomains: boolean;
  preload: boolean;
}

/** Shared shape for the simple present/value headers (CSP, XFO, XCTO, referrer, permissions). */
export interface HeaderPresence {
  present: boolean;
  value: string | null;
}

export interface HeadersData {
  final_url: string;
  status_code: number;
  redirect_chain: string[];
  http_to_https_redirect: boolean;
  hsts: HstsData;
  content_security_policy: HeaderPresence;
  x_content_type_options: HeaderPresence;
  x_frame_options: HeaderPresence;
  referrer_policy: HeaderPresence;
  permissions_policy: HeaderPresence;
  server_header: string | null;
  missing: string[];
}

export interface ReadinessData {
  // Nullable only when verdict === "unknown" (the certificate module
  // errored, so nothing about its lifetime is knowable — never guessed).
  current_lifetime_days: number | null;
  current_phase: LifetimePhase;
  phase_label: string;
  next_deadline: string;
  days_until_next_deadline: number;
  renewals_per_year_now: number | null;
  renewals_per_year_2027: number | null;
  renewals_per_year_2029: number | null;
  verdict: ReadinessVerdict;
  verdict_label: string;
  verdict_reason: string;
  survives_2027: boolean | null;
  survives_2029: boolean | null;
  message: string;
}

// --- 6.3 Finding ---

export interface Finding {
  code: string;
  module: ModuleName;
  severity: Severity;
  title: string;
  description: string;
  remediation: string;
  evidence: Record<string, unknown>;
  docs_path: string;
}

// --- 6.2 ModuleResult — uniform wrapper, generic over the module's data shape ---

export interface ModuleResult<TData> {
  module: ModuleName;
  status: ModuleStatus;
  score: number | null;
  grade: Grade | null;
  label: string;
  summary: string;
  checked_at: string;
  duration_ms: number;
  findings: Finding[];
  data: TData | null;
  error: string | null;
}

/** All seven keys are always present, per contract §6.1 — even mid-scan, as null entries. */
export interface Modules {
  certificate: ModuleResult<CertificateData> | null;
  chain: ModuleResult<ChainData> | null;
  tls: ModuleResult<TlsData> | null;
  dns: ModuleResult<DnsData> | null;
  email_auth: ModuleResult<EmailAuthData> | null;
  headers: ModuleResult<HeadersData> | null;
  readiness: ModuleResult<ReadinessData> | null;
}

// --- 6.1 Scan ---

export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
}

export interface Scan {
  scan_id: string;
  public_slug: string;
  hostname: string;
  port: number;
  status: ScanStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  cached: boolean;

  overall_grade: Grade | null;
  overall_score: number | null;
  headline: string | null;
  share_url: string;

  counts: SeverityCounts | null;

  modules: Modules;

  findings: Finding[];

  error: ApiError | null;
}

// --- 7.1 POST /api/v1/scans ---

export interface ScanCreateRequest {
  hostname: string;
  port?: number;
}

export interface ScanCreateResponse {
  scan_id: string;
  public_slug: string;
  status: ScanStatus;
  poll_url: string;
  share_url: string;
  cached: boolean;
}

// --- 6.5 MetaDeadlines — GET /api/v1/meta/deadlines ---

export interface PhaseInfo {
  phase: LifetimePhase;
  effective_from: string;
  max_lifetime_days: number;
  dcv_reuse_days: number;
  renewals_per_year: number;
  active: boolean;
}

export interface NextDeadlineInfo {
  phase: LifetimePhase;
  date: string;
  days_remaining: number;
}

export interface MetaDeadlines {
  generated_at: string;
  phases: PhaseInfo[];
  next_deadline: NextDeadlineInfo;
}
