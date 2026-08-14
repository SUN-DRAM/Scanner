import { describe, expect, it, vi } from "vitest";

// layout.tsx calls next/font/google at module scope; that loader only works
// inside Next's own build pipeline, not a plain vitest/node import, so it's
// mocked here purely to make the module importable — unrelated to what
// these tests actually assert.
vi.mock("next/font/google", () => ({
  Space_Grotesk: () => ({ variable: "--font-space-grotesk" }),
  Inter: () => ({ variable: "--font-inter" }),
  JetBrains_Mono: () => ({ variable: "--font-jetbrains-mono" }),
}));

import { metadata as layoutMetadata } from "./layout";
import { metadata as countdownMetadata } from "./countdown/page";
import { generateMetadata as generateFindingMetadata } from "./docs/findings/[code]/page";

describe("canonical URLs (Phase 2 Step 0.2 follow-up)", () => {
  it("root layout defaults canonical to the homepage", () => {
    expect(layoutMetadata.alternates).toEqual({ canonical: "/" });
  });

  it("a static route sets its own canonical path", () => {
    expect(countdownMetadata.alternates).toEqual({ canonical: "/countdown" });
  });

  it("a dynamic route (docs/findings/[code]) derives canonical from the slug", async () => {
    const result = await generateFindingMetadata({
      params: Promise.resolve({ code: "cert-expired" }),
    });
    expect(result.alternates).toEqual({ canonical: "/docs/findings/cert-expired" });
  });

  it("a dynamic route does not fabricate a canonical for an unknown slug", async () => {
    const result = await generateFindingMetadata({
      params: Promise.resolve({ code: "not-a-real-finding" }),
    });
    expect(result.alternates).toBeUndefined();
  });
});

describe("canonical URL for /scan/[slug] (Phase 2 Step 0.2 follow-up)", () => {
  it("derives canonical from the scan slug, independent of API host", async () => {
    vi.resetModules();
    vi.doMock("@/lib/api", () => ({
      getScanBySlug: vi.fn().mockResolvedValue({
        scan_id: "11111111-1111-1111-1111-111111111111",
        public_slug: "tWYyNJ8979Lg",
        hostname: "sundram.tech",
        port: 443,
        status: "completed",
        created_at: "2026-08-14T07:01:35Z",
        started_at: "2026-08-14T07:01:36Z",
        completed_at: "2026-08-14T07:01:38Z",
        duration_ms: 1932,
        cached: false,
        overall_grade: "A+",
        overall_score: 97,
        headline: "No serious problems found — 6 smaller improvements available.",
        share_url: "https://sundram.tech/scan/tWYyNJ8979Lg",
        counts: { critical: 0, high: 0, medium: 2, low: 2, info: 2 },
        modules: {},
        findings: [],
        error: null,
      }),
      ApiRequestError: class ApiRequestError extends Error {},
    }));

    const { generateMetadata } = await import("./scan/[slug]/page");
    const result = await generateMetadata({ params: Promise.resolve({ slug: "tWYyNJ8979Lg" }) });
    expect(result.alternates).toEqual({ canonical: "/scan/tWYyNJ8979Lg" });

    vi.doUnmock("@/lib/api");
  });
});
