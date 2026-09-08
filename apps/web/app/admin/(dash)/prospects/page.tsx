import Link from "next/link";

import { NewBatchForm } from "@/components/admin/NewBatchForm";
import { Badge } from "@/components/ui/badge";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { listAdminProspects } from "@/lib/api";
import { formatDateDisplay, gradeTone } from "@/lib/format";
import type { AdminProspectBatchRow, Grade } from "@/types/contract";

export const dynamic = "force-dynamic";

const PER_PAGE = 50;
const GRADE_BADGE_VARIANT = { pass: "pass", warn: "warn", alert: "alert" } as const;

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function GradeBadge({ grade }: { grade: Grade | null }) {
  if (grade === null) return <span className="text-ink-muted">—</span>;
  return <Badge variant={GRADE_BADGE_VARIANT[gradeTone(grade)]}>{grade}</Badge>;
}

function BatchRow({ batch }: { batch: AdminProspectBatchRow }) {
  const running = batch.scans_pending > 0;
  return (
    <tr className="border-b border-line last:border-b-0 hover:bg-paper">
      <td className="px-4 py-3">
        <Link
          href={`/admin/prospects/${batch.batch_id}`}
          className="font-medium text-ink hover:underline"
        >
          {batch.label}
        </Link>
        <p className="text-xs text-ink-muted">{formatDateDisplay(batch.created_at)}</p>
      </td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{batch.hostname_count}</td>
      <td className="px-4 py-3 text-sm text-ink-muted">
        {running ? `${batch.scans_completed}/${batch.hostname_count} scanned` : "Done"}
      </td>
      <td className="px-4 py-3">
        <GradeBadge grade={batch.worst_grade} />
      </td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{batch.expiring_60d_count}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">
        {batch.over_200day_lifetime_count}
      </td>
    </tr>
  );
}

export default async function AdminProspectsPage({ searchParams }: PageProps) {
  const token = await requireAdminToken();
  const sp = await searchParams;
  const pageParam = Array.isArray(sp.page) ? sp.page[0] : sp.page;
  const page = Math.max(1, Number.parseInt(pageParam ?? "1", 10) || 1);

  const data = await listAdminProspects({ page, per_page: PER_PAGE }, token).catch((err) =>
    redirectIfForbidden(err),
  );

  return (
    <div>
      <h1 className="mb-6 font-display text-xl leading-display text-ink">Prospects</h1>

      <section className="mb-10 rounded-card border border-line bg-surface p-4">
        <h2 className="mb-1 font-display text-base leading-display text-ink">New batch</h2>
        <p className="mb-4 text-sm text-ink-muted">
          Paste an agency&apos;s client portfolio. These scans belong to no account — they never
          schedule and never alert.
        </p>
        <NewBatchForm />
      </section>

      <h2 className="mb-3 font-display text-base leading-display text-ink">
        {data.total} batch{data.total === 1 ? "" : "es"}
      </h2>
      {data.total === 0 ? (
        <p className="rounded-card border border-line bg-surface px-6 py-12 text-center text-sm text-ink-muted">
          No batches yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-3 font-medium">Label</th>
                <th className="px-4 py-3 font-medium">Hostnames</th>
                <th className="px-4 py-3 font-medium">Progress</th>
                <th className="px-4 py-3 font-medium">Worst grade</th>
                <th className="px-4 py-3 font-medium">Expiring ≤60d</th>
                <th className="px-4 py-3 font-medium">Lifetime &gt;200d</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((batch) => (
                <BatchRow key={batch.batch_id} batch={batch} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
