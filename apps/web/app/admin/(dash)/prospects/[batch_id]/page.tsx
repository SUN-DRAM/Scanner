import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { ApiRequestError, getAdminProspectBatch } from "@/lib/api";
import { formatDateDisplay, gradeTone } from "@/lib/format";
import type { AdminProspectItem, Grade } from "@/types/contract";

export const dynamic = "force-dynamic";

const GRADE_BADGE_VARIANT = { pass: "pass", warn: "warn", alert: "alert" } as const;

interface PageProps {
  params: Promise<{ batch_id: string }>;
}

function GradeBadge({ grade }: { grade: Grade | null }) {
  if (grade === null) return <span className="text-ink-muted">—</span>;
  return <Badge variant={GRADE_BADGE_VARIANT[gradeTone(grade)]}>{grade}</Badge>;
}

function ItemRow({ item }: { item: AdminProspectItem }) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-3 font-mono text-xs text-ink">{item.hostname}</td>
      <td className="px-4 py-3">
        <GradeBadge grade={item.grade} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink">
        {item.days_to_expiry === null ? "—" : `${item.days_to_expiry}d`}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink">
        {item.cert_lifetime_days === null ? "—" : `${item.cert_lifetime_days}d`}
      </td>
      <td className="px-4 py-3 text-sm text-ink-muted">{item.status ?? "—"}</td>
      <td className="px-4 py-3">
        {item.share_url ? (
          <a
            href={item.share_url}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-xs text-ink underline hover:text-ink-muted"
          >
            {item.public_slug}
          </a>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

export default async function AdminProspectBatchPage({ params }: PageProps) {
  const token = await requireAdminToken();
  const { batch_id } = await params;

  const batch = await getAdminProspectBatch(batch_id, token).catch((err) => {
    if (err instanceof ApiRequestError && err.code === "NOT_FOUND") notFound();
    return redirectIfForbidden(err);
  });

  return (
    <div>
      <Link
        href="/admin/prospects"
        className="text-sm text-ink-muted hover:text-ink hover:underline"
      >
        ← All batches
      </Link>

      <div className="mb-6 mt-2 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl leading-display text-ink">{batch.label}</h1>
          <p className="text-sm text-ink-muted">
            {formatDateDisplay(batch.created_at)} · {batch.hostname_count} hostname
            {batch.hostname_count === 1 ? "" : "s"} ·{" "}
            {batch.scans_pending > 0
              ? `${batch.scans_completed}/${batch.hostname_count} scanned`
              : "all scanned"}
          </p>
        </div>
        <a
          href={`/admin/prospects/${batch.batch_id}/export`}
          className="rounded-control border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-paper"
        >
          Export CSV
        </a>
      </div>

      <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Worst grade" value={batch.worst_grade ?? "—"} />
        <Stat label="Expiring ≤60d" value={batch.expiring_60d_count} />
        <Stat label="Lifetime >200d" value={batch.over_200day_lifetime_count} />
        <Stat label="Completed" value={`${batch.scans_completed}/${batch.hostname_count}`} />
      </div>

      <div className="overflow-x-auto rounded-card border border-line bg-surface">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
              <th className="px-4 py-3 font-medium">Hostname</th>
              <th className="px-4 py-3 font-medium">Grade</th>
              <th className="px-4 py-3 font-medium">Expires in</th>
              <th className="px-4 py-3 font-medium">Cert lifetime</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Report</th>
            </tr>
          </thead>
          <tbody>
            {batch.items.map((item) => (
              <ItemRow key={item.hostname} item={item} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-card border border-line bg-surface px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 font-display text-xl leading-display text-ink">{value}</p>
    </div>
  );
}
