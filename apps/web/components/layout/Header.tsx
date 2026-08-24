import Link from "next/link";

import { Button } from "@/components/ui/button";

export function Header() {
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
              single line at the 360px floor. Sign in/Sign up stay visible
              at every width, ahead of Guides/API status/the countdown link,
              since they're the primary conversion action, not secondary
              navigation. */}
          <Link
            href="/countdown"
            className="hidden transition-colors hover:text-ink md:inline"
          >
            2027 countdown
          </Link>
          <Link href="/guides" className="hidden transition-colors hover:text-ink md:inline">
            Guides
          </Link>
          <Link href="/api-status" className="hidden transition-colors hover:text-ink md:inline">
            API status
          </Link>
          <Link href="/login" className="transition-colors hover:text-ink">
            Sign in
          </Link>
          <Button asChild size="sm">
            <Link href="/login">Sign up</Link>
          </Button>
        </nav>
      </div>
    </header>
  );
}
