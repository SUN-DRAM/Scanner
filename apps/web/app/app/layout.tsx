import type { Metadata } from "next";

import { DashboardShell } from "@/components/app/DashboardShell";
import { requireOrg } from "@/lib/session";

// §Step 7: "/app/* must be noindex and excluded in robots.ts — coordinate
// with the Step 0.2 fix so the two don't fight." robots.ts already
// disallows crawling /app/ entirely (Step 0.2); this is the second,
// independent layer for any crawler that reads a page anyway (link
// previews, crawlers that ignore robots.txt) — belt and suspenders, not a
// replacement for either.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // Every /app/* route is gated here, once — redirects to /login if there's
  // no valid session, so no individual page below has to repeat the check.
  const { me, org } = await requireOrg();

  return (
    <DashboardShell orgName={org.name} email={me.email}>
      {children}
    </DashboardShell>
  );
}
