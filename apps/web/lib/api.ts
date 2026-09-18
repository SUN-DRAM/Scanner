/**
 * The only place `fetch()` is called (contract §3.2). Every request the
 * frontend makes — server or client component — goes through here, typed
 * against `types/contract.ts`.
 */

import type {
  AccountHealth,
  AdminAccountDetail,
  AdminAccountRow,
  AdminAccountSort,
  AdminFunnelReport,
  AdminHealthReport,
  AdminProspectBatchDetail,
  AdminProspectBatchRow,
  AlertEvent,
  AlertRecipient,
  AlertRecipientCreateRequest,
  BillingCheckoutRequest,
  BillingCheckoutResponse,
  BillingPlansResponse,
  ErrorEnvelope,
  Invoice,
  MemberInviteRequest,
  MembershipWithEmail,
  MetaDeadlines,
  MonitorBulkRequest,
  MonitorBulkResponse,
  MonitorCreateRequest,
  MonitoredHostname,
  MonitorHistoryEntry,
  MonitorState,
  MonitorUpdateRequest,
  Organisation,
  OrgUpdateRequest,
  OtpVerifyRequest,
  OutreachCampaign,
  OutreachCampaignCreateRequest,
  OutreachCampaignRow,
  OutreachImportReport,
  OutreachProspectRow,
  OutreachProspectState,
  OutreachScanProgress,
  PaginatedList,
  PlanCode,
  Scan,
  ScanCreateRequest,
  ScanCreateResponse,
  Subscription,
  User,
  WaitlistCreateRequest,
  WaitlistCreateResponse,
} from "@/types/contract";

/**
 * Contract §4 gives the frontend exactly one API variable,
 * `NEXT_PUBLIC_API_BASE_URL` — but that's the address a *browser* should
 * use, and server-side code (`window` is undefined in Node) always runs
 * inside the `web` container itself, which is always a Docker Compose
 * sibling of `api`, in dev and in production alike. Routing a server-side
 * fetch through the public URL instead is both wasteful — a public-internet
 * round trip to reach a container one hop away — and, on many cloud
 * providers, outright broken: a server frequently cannot reach its own
 * public IP from inside itself (no hairpin NAT), so this would fail exactly
 * when it matters most, the very first self-render right after DNS goes
 * live. (Confirmed live: with `NEXT_PUBLIC_API_BASE_URL` set to the real
 * production domain, every server-rendered page 500'd with a connect
 * timeout until this was fixed to always use the internal service name
 * server-side, unconditionally — not just for the `localhost` dev case.)
 */
function resolveApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return "http://api:8000";
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
}

const API_BASE_URL = resolveApiBaseUrl();

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.error.message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = envelope.error.code;
    this.details = envelope.error.details;
    this.requestId = envelope.error.request_id;
  }
}

/** Thrown by `pollScan` when the 90s ceiling (contract §7.3) is reached
 * without the scan reaching a terminal status. Carries the last scan seen
 * so the caller can still show partial progress. */
export class ScanPollTimeoutError extends Error {
  readonly lastScan: Scan;

  constructor(lastScan: Scan) {
    super("Scan did not finish within the polling window.");
    this.name = "ScanPollTimeoutError";
    this.lastScan = lastScan;
  }
}

/**
 * `cookie` forwards the `sd_session` cookie (Phase 2 §7.6) on an
 * authenticated call. Browser-side callers never pass it — `credentials:
 * "include"` below already hands the browser's own cookie jar to a
 * same-site request. Server Components can't rely on that (Node's `fetch`
 * has no cookie jar of its own), so a page that needs authenticated data
 * reads its own request's cookies via `next/headers` and passes the string
 * through explicitly — kept out of this file so `next/headers` (a
 * Server-Component-only import) never has a reason to appear in a file a
 * "use client" component also imports.
 */
interface AuthedRequestOptions {
  cookie?: string;
  /** Contract §7.13: the internal admin surface authenticates with a single
   * shared token in the `X-Admin-Token` header, not the session cookie. The
   * `/admin/*` pages read the operator's `sd_admin` cookie server-side and
   * pass its value through here. */
  adminToken?: string;
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  options?: AuthedRequestOptions,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (options?.cookie) {
    headers.Cookie = options.cookie;
  }
  if (options?.adminToken) {
    headers["X-Admin-Token"] = options.adminToken;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });

  if (!response.ok) {
    const envelope = (await response.json()) as ErrorEnvelope;
    throw new ApiRequestError(response.status, envelope);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** `params` is always one of this file's own `*Params` interfaces — all
 * string/number/undefined leaves, never nested — so one cast here is safe
 * and keeps every call site plainly typed instead of casting repeatedly. */
function queryString(params: object): string {
  const entries = Object.entries(params as Record<string, string | number | undefined | null>).filter(
    (entry): entry is [string, string | number] => entry[1] !== undefined && entry[1] !== null,
  );
  if (entries.length === 0) return "";
  const search = new URLSearchParams(entries.map(([key, value]) => [key, String(value)]));
  return `?${search.toString()}`;
}

export interface PageParams {
  page?: number;
  per_page?: number;
}

export function createScan(request: ScanCreateRequest): Promise<ScanCreateResponse> {
  return apiFetch<ScanCreateResponse>("/api/v1/scans", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function getScan(scanId: string): Promise<Scan> {
  return apiFetch<Scan>(`/api/v1/scans/${encodeURIComponent(scanId)}`);
}

export function getScanBySlug(slug: string): Promise<Scan> {
  return apiFetch<Scan>(`/api/v1/scans/slug/${encodeURIComponent(slug)}`);
}

export function getDeadlines(): Promise<MetaDeadlines> {
  return apiFetch<MetaDeadlines>("/api/v1/meta/deadlines");
}

/**
 * Contract §7.14 (v2.9): a plain, public, unauthenticated GET returning
 * `application/pdf` — no JSON, no fetch/blob dance needed. Deliberately
 * *not* built on `resolveApiBaseUrl()`/`apiFetch`: those exist to route
 * server-side calls through the internal `http://api:8000` service name
 * (see that function's own comment), but this URL is only ever handed to
 * the browser as an `<a href>` — it must always be the public address, even
 * when the component rendering it first runs server-side during SSR.
 */
export function scanReportPdfUrl(scanId: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  return `${base}/api/v1/scans/${encodeURIComponent(scanId)}/report.pdf`;
}

export function submitWaitlist(request: WaitlistCreateRequest): Promise<WaitlistCreateResponse> {
  return apiFetch<WaitlistCreateResponse>("/api/v1/waitlist", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

// --- 7.6/7.7 Auth & organisation (Phase 2) ---

export function requestOtp(email: string): Promise<{ message: string }> {
  return apiFetch("/api/v1/auth/otp/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyOtp(request: OtpVerifyRequest): Promise<User> {
  return apiFetch<User>("/api/v1/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function logout(): Promise<{ message: string }> {
  return apiFetch("/api/v1/auth/logout", { method: "POST" });
}

export function getMe(cookie?: string): Promise<User> {
  return apiFetch<User>("/api/v1/auth/me", undefined, { cookie });
}

export function getCurrentOrg(cookie?: string): Promise<Organisation> {
  return apiFetch<Organisation>("/api/v1/orgs/current", undefined, { cookie });
}

export function updateCurrentOrg(
  request: OrgUpdateRequest,
  cookie?: string,
): Promise<Organisation> {
  return apiFetch<Organisation>(
    "/api/v1/orgs/current",
    { method: "PATCH", body: JSON.stringify(request) },
    { cookie },
  );
}

export function listMembers(
  params: PageParams = {},
  cookie?: string,
): Promise<PaginatedList<MembershipWithEmail>> {
  return apiFetch<PaginatedList<MembershipWithEmail>>(
    `/api/v1/orgs/current/members${queryString(params)}`,
    undefined,
    { cookie },
  );
}

export function inviteMember(
  request: MemberInviteRequest,
  cookie?: string,
): Promise<MembershipWithEmail> {
  return apiFetch<MembershipWithEmail>(
    "/api/v1/orgs/current/members",
    { method: "POST", body: JSON.stringify(request) },
    { cookie },
  );
}

export function removeMember(userId: string, cookie?: string): Promise<void> {
  return apiFetch<void>(
    `/api/v1/orgs/current/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
    { cookie },
  );
}

// --- 7.8/7.9 Monitored hostnames (Phase 2) ---

export interface ListMonitorsParams extends PageParams {
  state?: MonitorState;
}

export function listMonitors(
  params: ListMonitorsParams = {},
  cookie?: string,
): Promise<PaginatedList<MonitoredHostname>> {
  return apiFetch<PaginatedList<MonitoredHostname>>(
    `/api/v1/monitors${queryString(params)}`,
    undefined,
    { cookie },
  );
}

export function createMonitor(
  request: MonitorCreateRequest,
  cookie?: string,
): Promise<MonitoredHostname> {
  return apiFetch<MonitoredHostname>(
    "/api/v1/monitors",
    { method: "POST", body: JSON.stringify(request) },
    { cookie },
  );
}

export function getMonitor(monitorId: string, cookie?: string): Promise<MonitoredHostname> {
  return apiFetch<MonitoredHostname>(
    `/api/v1/monitors/${encodeURIComponent(monitorId)}`,
    undefined,
    { cookie },
  );
}

export function updateMonitor(
  monitorId: string,
  request: MonitorUpdateRequest,
  cookie?: string,
): Promise<MonitoredHostname> {
  return apiFetch<MonitoredHostname>(
    `/api/v1/monitors/${encodeURIComponent(monitorId)}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { cookie },
  );
}

export function deleteMonitor(monitorId: string, cookie?: string): Promise<void> {
  return apiFetch<void>(
    `/api/v1/monitors/${encodeURIComponent(monitorId)}`,
    { method: "DELETE" },
    { cookie },
  );
}

export function bulkCreateMonitors(
  request: MonitorBulkRequest,
  cookie?: string,
): Promise<MonitorBulkResponse> {
  return apiFetch<MonitorBulkResponse>(
    "/api/v1/monitors/bulk",
    { method: "POST", body: JSON.stringify(request) },
    { cookie },
  );
}

export function triggerManualScan(
  monitorId: string,
  cookie?: string,
): Promise<ScanCreateResponse> {
  return apiFetch<ScanCreateResponse>(
    `/api/v1/monitors/${encodeURIComponent(monitorId)}/scan`,
    { method: "POST" },
    { cookie },
  );
}

export function getMonitorHistory(
  monitorId: string,
  params: PageParams = {},
  cookie?: string,
): Promise<PaginatedList<MonitorHistoryEntry>> {
  return apiFetch<PaginatedList<MonitorHistoryEntry>>(
    `/api/v1/monitors/${encodeURIComponent(monitorId)}/history${queryString(params)}`,
    undefined,
    { cookie },
  );
}

export function getMonitorAlerts(
  monitorId: string,
  params: PageParams = {},
  cookie?: string,
): Promise<PaginatedList<AlertEvent>> {
  return apiFetch<PaginatedList<AlertEvent>>(
    `/api/v1/monitors/${encodeURIComponent(monitorId)}/alerts${queryString(params)}`,
    undefined,
    { cookie },
  );
}

// --- 7.12 Alert recipients (Phase 2 Step 7) ---

export function listRecipients(
  params: PageParams = {},
  cookie?: string,
): Promise<PaginatedList<AlertRecipient>> {
  return apiFetch<PaginatedList<AlertRecipient>>(
    `/api/v1/alerts/recipients${queryString(params)}`,
    undefined,
    { cookie },
  );
}

export function createRecipient(
  request: AlertRecipientCreateRequest,
  cookie?: string,
): Promise<AlertRecipient> {
  return apiFetch<AlertRecipient>(
    "/api/v1/alerts/recipients",
    { method: "POST", body: JSON.stringify(request) },
    { cookie },
  );
}

export function deleteRecipient(recipientId: string, cookie?: string): Promise<void> {
  return apiFetch<void>(
    `/api/v1/alerts/recipients/${encodeURIComponent(recipientId)}`,
    { method: "DELETE" },
    { cookie },
  );
}

// --- 7.11 Billing (Phase 2 Step 6) ---

export function getBillingPlans(cookie?: string): Promise<BillingPlansResponse> {
  return apiFetch<BillingPlansResponse>("/api/v1/billing/plans", undefined, { cookie });
}

export function createCheckout(
  request: BillingCheckoutRequest,
  cookie?: string,
): Promise<BillingCheckoutResponse> {
  return apiFetch<BillingCheckoutResponse>(
    "/api/v1/billing/checkout",
    { method: "POST", body: JSON.stringify(request) },
    { cookie },
  );
}

export function getSubscription(cookie?: string): Promise<Subscription | null> {
  return apiFetch<Subscription | null>("/api/v1/billing/subscription", undefined, { cookie });
}

export function cancelSubscription(cookie?: string): Promise<Subscription> {
  return apiFetch<Subscription>(
    "/api/v1/billing/cancel",
    { method: "POST" },
    { cookie },
  );
}

export function listInvoices(
  params: PageParams = {},
  cookie?: string,
): Promise<PaginatedList<Invoice>> {
  return apiFetch<PaginatedList<Invoice>>(
    `/api/v1/billing/invoices${queryString(params)}`,
    undefined,
    { cookie },
  );
}

// --- 7.13 Admin surface (internal) ---

export interface ListAdminAccountsParams extends PageParams {
  plan?: PlanCode;
  health?: AccountHealth;
  signed_up_after?: string;
  signed_up_before?: string;
  sort?: AdminAccountSort;
}

export function listAdminAccounts(
  params: ListAdminAccountsParams,
  adminToken: string,
): Promise<PaginatedList<AdminAccountRow>> {
  return apiFetch<PaginatedList<AdminAccountRow>>(
    `/api/v1/admin/accounts${queryString(params)}`,
    undefined,
    { adminToken },
  );
}

export function getAdminAccount(
  orgId: string,
  adminToken: string,
): Promise<AdminAccountDetail> {
  return apiFetch<AdminAccountDetail>(
    `/api/v1/admin/accounts/${encodeURIComponent(orgId)}`,
    undefined,
    { adminToken },
  );
}

export function getAdminHealth(adminToken: string): Promise<AdminHealthReport> {
  return apiFetch<AdminHealthReport>("/api/v1/admin/health", undefined, { adminToken });
}

export function getAdminFunnel(adminToken: string): Promise<AdminFunnelReport> {
  return apiFetch<AdminFunnelReport>("/api/v1/admin/funnel", undefined, { adminToken });
}

export function listAdminProspects(
  params: PageParams,
  adminToken: string,
): Promise<PaginatedList<AdminProspectBatchRow>> {
  return apiFetch<PaginatedList<AdminProspectBatchRow>>(
    `/api/v1/admin/prospects${queryString(params)}`,
    undefined,
    { adminToken },
  );
}

export function getAdminProspectBatch(
  batchId: string,
  adminToken: string,
): Promise<AdminProspectBatchDetail> {
  return apiFetch<AdminProspectBatchDetail>(
    `/api/v1/admin/prospects/${encodeURIComponent(batchId)}`,
    undefined,
    { adminToken },
  );
}

export function createAdminProspectBatch(
  label: string,
  hostnames: string[],
  adminToken: string,
): Promise<AdminProspectBatchDetail> {
  return apiFetch<AdminProspectBatchDetail>(
    "/api/v1/admin/prospects",
    { method: "POST", body: JSON.stringify({ label, hostnames }) },
    { adminToken },
  );
}

/** Raw fetch for the CSV — the caller (a route handler) streams the body
 * back to the browser with the download headers. */
export async function fetchAdminProspectCsv(
  batchId: string,
  adminToken: string,
): Promise<{ status: number; body: string; contentDisposition: string | null }> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/admin/prospects/${encodeURIComponent(batchId)}/export`,
    { headers: { "X-Admin-Token": adminToken }, cache: "no-store" },
  );
  return {
    status: response.status,
    body: await response.text(),
    contentDisposition: response.headers.get("content-disposition"),
  };
}

// --- §7.15 Outreach orchestrator, Stage 1 admin surface (v3.6) ---

export function createOutreachCampaign(
  name: string,
  adminToken: string,
): Promise<OutreachCampaign> {
  const request: OutreachCampaignCreateRequest = { name };
  return apiFetch<OutreachCampaign>(
    "/api/v1/admin/outreach/campaigns",
    { method: "POST", body: JSON.stringify(request) },
    { adminToken },
  );
}

export function listOutreachCampaigns(
  params: PageParams,
  adminToken: string,
): Promise<PaginatedList<OutreachCampaignRow>> {
  return apiFetch<PaginatedList<OutreachCampaignRow>>(
    `/api/v1/admin/outreach/campaigns${queryString(params)}`,
    undefined,
    { adminToken },
  );
}

export function getOutreachCampaign(
  campaignId: string,
  adminToken: string,
): Promise<OutreachCampaignRow> {
  return apiFetch<OutreachCampaignRow>(
    `/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}`,
    undefined,
    { adminToken },
  );
}

export interface OutreachProspectListParams extends PageParams {
  state?: OutreachProspectState;
}

export function listOutreachProspects(
  campaignId: string,
  params: OutreachProspectListParams,
  adminToken: string,
): Promise<PaginatedList<OutreachProspectRow>> {
  return apiFetch<PaginatedList<OutreachProspectRow>>(
    `/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}/prospects${queryString(params)}`,
    undefined,
    { adminToken },
  );
}

/** Raw fetch, not `apiFetch` — a multipart body needs the browser's own
 * `Content-Type: multipart/form-data; boundary=...` header, which
 * `apiFetch`'s hardcoded `application/json` would silently override. */
export async function importOutreachCampaignCsv(
  campaignId: string,
  file: File,
  adminToken: string,
): Promise<OutreachImportReport> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(
    `${API_BASE_URL}/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}/import`,
    { method: "POST", headers: { "X-Admin-Token": adminToken }, body: formData, cache: "no-store" },
  );
  if (!response.ok) {
    const envelope = (await response.json()) as ErrorEnvelope;
    throw new ApiRequestError(response.status, envelope);
  }
  return (await response.json()) as OutreachImportReport;
}

// --- §7.16 Outreach orchestrator, Stage 2 batch control (v3.9/v3.10) ---

export function startOutreachScan(
  campaignId: string,
  includeWeak: boolean,
  adminToken: string,
): Promise<OutreachCampaignRow> {
  return apiFetch<OutreachCampaignRow>(
    `/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}/scan${queryString({
      include_weak: includeWeak ? "true" : undefined,
    })}`,
    { method: "POST" },
    { adminToken },
  );
}

export function pauseOutreachScan(
  campaignId: string,
  adminToken: string,
): Promise<OutreachCampaignRow> {
  return apiFetch<OutreachCampaignRow>(
    `/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}/pause`,
    { method: "POST" },
    { adminToken },
  );
}

export function resumeOutreachScan(
  campaignId: string,
  adminToken: string,
): Promise<OutreachCampaignRow> {
  return apiFetch<OutreachCampaignRow>(
    `/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}/resume`,
    { method: "POST" },
    { adminToken },
  );
}

export function getOutreachScanProgress(
  campaignId: string,
  adminToken: string,
): Promise<OutreachScanProgress> {
  return apiFetch<OutreachScanProgress>(
    `/api/v1/admin/outreach/campaigns/${encodeURIComponent(campaignId)}/scan-progress`,
    undefined,
    { adminToken },
  );
}

/** Mirrors `apps/api/app/routers/health.py`'s `HealthResponse` — an ad hoc
 * shape outside `schemas.py`, so it isn't in `types/contract.ts` either. */
export interface HealthStatus {
  status: "ok" | "degraded";
  database: "ok" | "error";
  redis: "ok" | "error";
  version: string;
  checked_at: string;
}

export function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/api/v1/health");
}

const TERMINAL_STATUSES = new Set<Scan["status"]>(["completed", "failed"]);

export interface PollScanOptions {
  /** Contract §7.3: 1500ms. */
  intervalMs?: number;
  /** Contract §7.3: 90s ceiling. */
  timeoutMs?: number;
  onUpdate?: (scan: Scan) => void;
  signal?: AbortSignal;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

/** Polls `GET /api/v1/scans/{scan_id}` per contract §7.3: every 1500ms,
 * gives up after 90s, stops immediately on `completed` or `failed`. */
export async function pollScan(scanId: string, options: PollScanOptions = {}): Promise<Scan> {
  const intervalMs = options.intervalMs ?? 1500;
  const timeoutMs = options.timeoutMs ?? 90_000;
  const startedAt = Date.now();

  let scan = await getScan(scanId);
  options.onUpdate?.(scan);

  while (!TERMINAL_STATUSES.has(scan.status)) {
    if (Date.now() - startedAt >= timeoutMs) {
      throw new ScanPollTimeoutError(scan);
    }
    await delay(intervalMs, options.signal);
    scan = await getScan(scanId);
    options.onUpdate?.(scan);
  }

  return scan;
}
