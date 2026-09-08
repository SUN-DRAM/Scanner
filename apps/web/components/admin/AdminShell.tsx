"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { signOutAdmin } from "@/app/admin/actions";
import { cn } from "@/lib/format";

const NAV_LINKS = [
  { href: "/admin/accounts", label: "Accounts" },
  { href: "/admin/prospects", label: "Prospects" },
  { href: "/admin/funnel", label: "Funnel" },
  { href: "/admin/health", label: "Health" },
] as const;

/** Deliberately monochrome (contract §12 tokens, no cobalt accent): this is
 * an operator instrument, not a customer surface. */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOutAdmin();
    } finally {
      router.push("/admin/login");
      router.refresh();
    }
  }

  return (
    <div>
      <div className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-content flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <span className="font-display text-sm tracking-wide text-ink">SUN-DRAM admin</span>
          <nav className="flex items-center gap-1">
            {NAV_LINKS.map((link) => {
              const active = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-control px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-ink text-surface"
                      : "text-ink-muted hover:bg-paper hover:text-ink",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <button
            type="button"
            onClick={handleSignOut}
            disabled={signingOut}
            className="ml-auto text-sm font-medium text-ink-muted transition-colors hover:text-ink hover:underline disabled:opacity-50"
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </div>
      <div className="mx-auto max-w-content px-4 py-10">{children}</div>
    </div>
  );
}
