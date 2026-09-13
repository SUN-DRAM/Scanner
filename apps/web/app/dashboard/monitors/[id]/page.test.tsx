import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { MonitoredHostname, Scan } from "@/types/contract";

// The monitor detail page pulls in the `MonitorActions` client component,
// which calls `useRouter()` at render — stub `next/navigation` so a plain
// server render doesn't need the App Router runtime.
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("notFound() called");
  },
  useRouter: () => ({ refresh: () => {}, push: () => {} }),
  usePathname: () => "/dashboard/monitors/m-1",
}));

vi.mock("@/lib/session", () => ({
  getForwardedCookie: vi.fn().mockResolvedValue("sd_session=test"),
}));

const NULL_MODULES: Scan["modules"] = {
  certificate: null,
  chain: null,
  tls: null,
  dns: null,
  email_auth: null,
  headers: null,
  readiness: null,
};

const COMPLETED_SCAN: Scan = {
  scan_id: "22222222-2222-2222-2222-222222222222",
  public_slug: "abc123abc123",
  hostname: "sundram.tech",
  port: 443,
  status: "completed",
  created_at: "2026-09-08T09:00:00Z",
  started_at: "2026-09-08T09:00:01Z",
  completed_at: "2026-09-08T09:00:04Z",
  duration_ms: 3000,
  cached: false,
  overall_grade: "B",
  overall_score: 82,
  headline: "One high-severity issue to fix, plus 3 smaller improvements.",
  share_url: "https://sundram.tech/scan/abc123abc123",
  grade_cap_reason: null,
  is_complete: true,
  incomplete_modules: [],
  counts: { critical: 0, high: 1, medium: 1, low: 2, info: 0 },
  modules: NULL_MODULES,
  findings: [],
  error: null,
};

const MONITOR: MonitoredHostname = {
  monitor_id: "m-1",
  org_id: "o-1",
  hostname: "sundram.tech",
  port: 443,
  state: "active",
  label: null,
  notes: null,
  last_scan_id: COMPLETED_SCAN.scan_id,
  last_grade: "B",
  last_score: 82,
  last_scanned_at: "2026-09-08T09:00:04Z",
  next_scan_at: "2026-09-09T09:00:00Z",
  days_until_expiry: 60,
  created_at: "2026-09-08T08:59:00Z",
};

vi.mock("@/lib/api", () => ({
  ApiRequestError: class ApiRequestError extends Error {
    code: string;
    constructor(code: string, message: string) {
      super(message);
      this.code = code;
    }
  },
  ScanPollTimeoutError: class ScanPollTimeoutError extends Error {},
  getMonitor: vi.fn().mockResolvedValue(MONITOR),
  getMonitorHistory: vi
    .fn()
    .mockResolvedValue({ items: [], page: 1, per_page: 30, total: 0 }),
  getMonitorAlerts: vi
    .fn()
    .mockResolvedValue({ items: [], page: 1, per_page: 20, total: 0 }),
  getScan: vi.fn().mockResolvedValue(COMPLETED_SCAN),
  pollScan: vi.fn().mockResolvedValue(COMPLETED_SCAN),
  submitWaitlist: vi.fn(),
  scanReportPdfUrl: vi.fn((scanId: string) => `https://api.test/api/v1/scans/${scanId}/report.pdf`),
}));

describe("dashboard monitor detail page", () => {
  it("renders the overall grade, score and headline for a completed scan", async () => {
    const { default: MonitorDetailPage } = await import("./page");

    const element = await MonitorDetailPage({ params: Promise.resolve({ id: "m-1" }) });
    const html = renderToStaticMarkup(element);

    // The grade header regression: ScanResultBody was reused for the
    // dashboard but the grade dial/score/headline stayed behind in
    // ScanResultView. All three must render here.
    expect(html).toContain("Grade B");
    expect(html).toContain("82/100");
    expect(html).toContain("One high-severity issue to fix");
    // Colour never stands alone (contract §12): a text label rides with it.
    expect(html).toContain("Needs attention");
  });

  it("renders the same grade block as the public scan page for one scan_id", async () => {
    const { default: MonitorDetailPage } = await import("./page");
    const { ScanResultView } = await import("@/components/scan/ScanResultView");

    const dashboardHtml = renderToStaticMarkup(
      await MonitorDetailPage({ params: Promise.resolve({ id: "m-1" }) }),
    );
    const publicHtml = renderToStaticMarkup(<ScanResultView initialScan={COMPLETED_SCAN} />);

    // Both pages route the grade through the shared `ScanGradeHeader`, so the
    // dial (with its aria-label), the score, and the letter+label line are
    // byte-identical on each.
    for (const fragment of [
      'aria-label="Overall grade B, score 82 out of 100"',
      "82/100",
      "Grade B",
      "Needs attention",
    ]) {
      expect(publicHtml, `public page missing: ${fragment}`).toContain(fragment);
      expect(dashboardHtml, `dashboard page missing: ${fragment}`).toContain(fragment);
    }
  });

  it("shows Incomplete and the partial-assessment banner when certificate didn't complete", async () => {
    // PDF_FIXES.md Fix 2 / contract v3.0: no letter grade, never a blank
    // space where one would have been, plus the banner naming the count.
    const { ScanResultView } = await import("@/components/scan/ScanResultView");
    const incompleteScan: Scan = {
      ...COMPLETED_SCAN,
      overall_grade: null,
      overall_score: null,
      headline:
        "This assessment could not be completed — the certificate check didn't finish, " +
        "so there's no grade to show. Try scanning again.",
      is_complete: false,
      incomplete_modules: ["certificate", "chain", "tls"],
    };

    const html = renderToStaticMarkup(<ScanResultView initialScan={incompleteScan} />);

    expect(html).toContain("Incomplete");
    expect(html).toContain("3 of 7 checks did not complete");
    expect(html).toContain("This assessment is partial and should not be treated as a clean result");
    expect(html).not.toContain("Grade B");
  });

  it("shows the cap reason when the letter disagrees with the score", async () => {
    // PDF_FIXES.md polish: 82 bands to B, but two high-severity findings
    // capped the letter to C — the reader must see why, not just the two
    // conflicting numbers.
    const { ScanResultView } = await import("@/components/scan/ScanResultView");
    const cappedScan: Scan = {
      ...COMPLETED_SCAN,
      overall_grade: "C",
      overall_score: 82,
      grade_cap_reason: "capped by 2 high-severity findings",
    };

    const html = renderToStaticMarkup(<ScanResultView initialScan={cappedScan} />);

    expect(html).toContain("82/100");
    expect(html).toContain("Grade C");
    expect(html).toContain("C — capped by 2 high-severity findings");
  });
});
