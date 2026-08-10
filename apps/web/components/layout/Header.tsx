import Link from "next/link";

export function Header() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-16 max-w-content items-center justify-between px-4">
        <Link href="/" className="font-display text-base text-ink">
          SUN-DRAM<span className="text-cobalt"> Scanner</span>
        </Link>
        <nav className="flex items-center gap-4 text-sm text-ink-muted sm:gap-6">
          <Link href="/countdown" className="transition-colors hover:text-ink">
            2027 countdown
          </Link>
          {/* The contract's narrowest breakpoint (`sm`) is 360px itself, so
              there's no smaller step to hide these below — gate on `md`
              (768px) instead, the next one up, to keep the header to a
              single line at the 360px floor. */}
          <Link href="/guides" className="hidden transition-colors hover:text-ink md:inline">
            Guides
          </Link>
          <Link href="/api-status" className="hidden transition-colors hover:text-ink md:inline">
            API status
          </Link>
        </nav>
      </div>
    </header>
  );
}
