/**
 * The only place `fetch()` is called (contract §3.2). Every request the
 * frontend makes — server or client component — goes through here, typed
 * against `types/contract.ts`.
 */

import type {
  ErrorEnvelope,
  MetaDeadlines,
  Scan,
  ScanCreateRequest,
  ScanCreateResponse,
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

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const envelope = (await response.json()) as ErrorEnvelope;
    throw new ApiRequestError(response.status, envelope);
  }
  return (await response.json()) as T;
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

export function submitWaitlist(request: WaitlistCreateRequest): Promise<WaitlistCreateResponse> {
  return apiFetch<WaitlistCreateResponse>("/api/v1/waitlist", {
    method: "POST",
    body: JSON.stringify(request),
  });
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
