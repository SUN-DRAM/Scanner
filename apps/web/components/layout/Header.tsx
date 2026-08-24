import Link from "next/link";

import { SignOutButton } from "@/components/layout/SignOutButton";
import { Button } from "@/components/ui/button";
import { ApiRequestError, getMe } from "@/lib/api";
import { getForwardedCookie } from "@/lib/session";
import type { User } from "@/types/contract";

/** Same "does a valid session exist" check `lib/session.ts`'s `requireUser`
 * makes, without the redirect — the header renders on every route,
 * authenticated or not, so `UNAUTHENTICATED` is a normal outcome here, not
 * one to bounce away from. */
async function getCurrentUser(): Promise<User | null> {
  const cookie = await getForwardedCookie();
  try {
    return await getMe(cookie);
  } catch (err) {
    if (err instanceof ApiRequestError && err.code === "UNAUTHENTICATED") {
      return null;
    }
    throw err;
  }
}

export async function Header() {
  const user = await getCurrentUser();

  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-16 max-w-content items-center justify-between px-4">
        <Link href="/" className="font-display text-base text-ink">
          SUN-DRAM<span className="text-cobalt"> Scanner</span>
        </Link>
        <nav className="flex items-center gap-4 text-sm text-ink-muted sm:gap-6">
          {/* The contract's narrowest breakpoint (`sm`) is 360px itself, so
              there's no smaller step to hide these below — gate on `md`
              (768px) instead, the next one up, to keep the header to a
              single line at the 360px floor. The single primary action
              (Sign up, or Sign out once logged in) stays visible at every
              width; everything else is secondary and collapses first. */}
          <Link href="/countdown" className="hidden transition-colors hover:text-ink md:inline">
            2027 countdown
          </Link>
          <Link href="/guides" className="hidden transition-colors hover:text-ink md:inline">
            Guides
          </Link>
          <Link href="/api-status" className="hidden transition-colors hover:text-ink md:inline">
            API status
          </Link>
          {user ? (
            <>
              <Link href="/app" className="hidden transition-colors hover:text-ink sm:inline">
                Dashboard
              </Link>
              <span className="hidden lg:inline">{user.email}</span>
              <SignOutButton />
            </>
          ) : (
            <Button asChild size="sm">
              <Link href="/login">Sign up</Link>
            </Button>
          )}
        </nav>
      </div>
    </header>
  );
}
