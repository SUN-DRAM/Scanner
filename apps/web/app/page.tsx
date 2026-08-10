import Link from "next/link";

import { ScanForm } from "@/components/scan/ScanForm";
import { getDeadlines } from "@/lib/api";
import { formatIsoDateDisplay } from "@/lib/format";

export default async function HomePage() {
  const deadlines = await getDeadlines();
  const { next_deadline: nextDeadline } = deadlines;

  return (
    <main className="mx-auto flex max-w-content flex-col items-center gap-6 px-4 py-16 text-center sm:py-24">
      <p className="text-sm font-medium text-cobalt">
        Certificate lifetimes drop to 100 days on 15 March 2027.
      </p>
      <h1 className="max-w-reading font-display text-2xl leading-display text-ink sm:text-3xl md:text-4xl">
        Find out if your certificates and DNS will survive the cut.
      </h1>
      <p className="max-w-reading text-ink-muted">
        Enter a hostname. Get a graded TLS and DNS report in under 20 seconds — free, no signup.
      </p>

      <ScanForm />

      <Link
        href="/countdown"
        className="mt-8 flex flex-col items-center gap-1 rounded-card border border-line bg-surface px-8 py-5 transition-colors hover:border-cobalt"
      >
        <span className="font-mono text-3xl text-ink">{nextDeadline.days_remaining} days</span>
        <span className="text-xs text-ink-muted">
          until the {formatIsoDateDisplay(nextDeadline.date)} deadline — full countdown
        </span>
      </Link>
    </main>
  );
}
