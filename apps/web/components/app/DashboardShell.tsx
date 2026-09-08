"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/format";

const NAV_LINKS = [
  { href: "/app", label: "Hostnames" },
  { href: "/app/alerts", label: "Alerts" },
  { href: "/app/billing", label: "Billing" },
  { href: "/app/team", label: "Team" },
] as const;

interface DashboardShellProps {
  orgName: string;
  children: React.ReactNode;
}

/** The logged-in instrument's chrome — the app-specific nav §Step 7's seven
 * pages share, plus the current org name for context. Identity (the signed-in
 * email) and "Sign out" live once, in RootLayout's `Header`, which renders
 * above this on every route; they are deliberately not repeated here. */
export function DashboardShell({ orgName, children }: DashboardShellProps) {
  const pathname = usePathname();

  return (
    <div>
      <div className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-content flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <nav className="flex flex-wrap items-center gap-1">
            {NAV_LINKS.map((link) => {
              const active =
                link.href === "/app" ? pathname === "/app" : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-control px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-cobalt-soft text-cobalt"
                      : "text-ink-muted hover:bg-paper hover:text-ink",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-sm text-ink-muted">
            <span className="hidden font-medium text-ink sm:inline">{orgName}</span>
          </div>
        </div>
      </div>
      <div className="mx-auto max-w-content px-4 py-10">{children}</div>
    </div>
  );
}
