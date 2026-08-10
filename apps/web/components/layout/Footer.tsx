export function Footer() {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="mx-auto flex max-w-content flex-col gap-2 px-4 py-8 text-xs text-ink-muted sm:flex-row sm:items-center sm:justify-between">
        <p>SUN-DRAM Scanner. Read-only checks, no signup, no scan history kept against you.</p>
        <p>Client IP addresses are hashed, never stored raw.</p>
      </div>
    </footer>
  );
}
