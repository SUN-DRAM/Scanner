import type { Metadata } from "next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getDeadlines } from "@/lib/api";
import { formatIsoDateDisplay } from "@/lib/format";

export const metadata: Metadata = {
  title: "2027 certificate lifetime countdown",
  description: "The CA/Browser Forum's certificate lifetime phase-down, and what changes when.",
};

const PHASE_LABEL: Record<string, string> = {
  phase_200: "200-day maximum",
  phase_100: "100-day maximum",
  phase_47: "47-day maximum",
};

export default async function CountdownPage() {
  const deadlines = await getDeadlines();

  return (
    <main className="mx-auto max-w-content px-4 py-16">
      <div className="mx-auto max-w-reading text-center">
        <p className="text-sm font-medium text-cobalt">Next deadline</p>
        <p className="mt-2 font-display text-3xl leading-display text-ink sm:text-4xl">
          {deadlines.next_deadline.days_remaining} days
        </p>
        <p className="mt-2 text-ink-muted">
          until {formatIsoDateDisplay(deadlines.next_deadline.date)}, when maximum certificate
          lifetime drops to {PHASE_LABEL[deadlines.next_deadline.phase] ?? "a shorter maximum"}.
        </p>
      </div>

      {/* `sm` is the contract's 360px floor, not a "wider phone" step up —
          three columns needs the room `md` (768px) actually provides. */}
      <div className="mt-12 grid gap-4 md:grid-cols-3">
        {deadlines.phases.map((phase) => (
          <Card key={phase.phase} className={phase.active ? "border-cobalt" : undefined}>
            <CardHeader>
              <CardTitle>{PHASE_LABEL[phase.phase] ?? phase.phase}</CardTitle>
              {phase.active ? (
                <span className="w-fit rounded-control bg-cobalt-soft px-2 py-0.5 text-xs font-medium text-cobalt">
                  In force now
                </span>
              ) : null}
            </CardHeader>
            <CardContent className="flex flex-col gap-2 font-mono text-sm text-ink-muted">
              <p>Effective from {formatIsoDateDisplay(phase.effective_from)}</p>
              <p>Max lifetime: {phase.max_lifetime_days} days</p>
              <p>DCV reuse: {phase.dcv_reuse_days} days</p>
              <p>Renewals/year: {phase.renewals_per_year}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </main>
  );
}
