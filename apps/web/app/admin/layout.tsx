import type { Metadata } from "next";

// §7.13: `/admin/*` stays out of search two independent ways, matching
// `/app/*` — `robots.ts` already disallows the path (Step 0.2), and this
// sets `noindex` for any crawler that reads the page regardless.
export const metadata: Metadata = {
  title: "Admin",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
