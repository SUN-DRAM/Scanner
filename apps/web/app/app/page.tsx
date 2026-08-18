import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { listMonitors } from "@/lib/api";
import { formatDateTimeDisplay, gradeTone } from "@/lib/format";
import { getForwardedCookie } from "@/lib/session";
import type { Grade, MonitoredHostname, MonitorState } from "@/types/contract";

export const metadata: Metadata = { title: "Hostnames" };

const STATE_LABEL: Record<MonitorState, string> = {
  active: "Active",
  paused: "Paused",
  quota_blocked: "Over plan limit",
  verification_pending: "Verifying",
};

const STATE_VARIANT: Record<MonitorState, "pass" | "neutral" | "warn"> = {
  active: "pass",
  paused: "neutral",
  quota_blocked: "warn",
  verification_pending: "neutral",
};

const GRADE_BADGE_VARIANT = { pass: "pass", warn: "warn", alert: "alert" } as const;

function daysUntilExpiryLabel(days: number | null): string {
  if (days === null) return "—";
  if (days < 0) return "Expired";
  if (days === 0) return "Today";
  return `${days} day${days === 1 ? "" : "s"}`;
}

function GradeBadge({ grade }: { grade: Grade | null }) {
  if (grade === null) return <span className="text-ink-muted">—</span>;
  return <Badge variant={GRADE_BADGE_VARIANT[gradeTone(grade)]}>{grade}</Badge>;
}

function MonitorRow({ monitor }: { monitor: MonitoredHostname }) {
  return (
    <tr className="border-b border-line last:border-b-0 hover:bg-paper">
      <td className="px-4 py-3">
        <Link
          href={`/app/monitors/${monitor.monitor_id}`}
          className="font-mono text-sm text-ink hover:text-cobalt hover:underline"
        >
          {monitor.hostname}
          {monitor.port !== 443 ? `:${monitor.port}` : ""}
        </Link>
        {monitor.label ? <p className="text-xs text-ink-muted">{monitor.label}</p> : null}
      </td>
      <td className="px-4 py-3">
        <GradeBadge grade={monitor.last_grade} />
      </td>
      <td className="py-3 pr-4 font-mono text-sm text-ink">
        {daysUntilExpiryLabel(monitor.days_until_expiry)}
      </td>
      <td className="py-3 pr-4 text-sm text-ink-muted">
        {monitor.last_scanned_at ? formatDateTimeDisplay(monitor.last_scanned_at) : "Not yet"}
      </td>
      <td className="px-4 py-3">
        <Badge variant={STATE_VARIANT[monitor.state]}>{STATE_LABEL[monitor.state]}</Badge>
      </td>
    </tr>
  );
}

export default async function HostnamesPage() {
  const cookie = await getForwardedCookie();
  // Default sort is soonest-expiry-first server-side (§7.8) — no sort
  // param exists to override it, "that column is the product" (§Step 7).
  const monitors = await listMonitors({ per_page: 100 }, cookie);

  if (monitors.total === 0) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-card border border-line bg-surface px-6 py-16 text-center">
        <h1 className="font-display text-xl leading-display text-ink">
          Watch your first certificate
        </h1>
        <p className="max-w-reading text-sm leading-prose text-ink-muted">
          Add a hostname and we&apos;ll re-scan it on a schedule, then email you before its
          certificate or domain expires.
        </p>
        <Button asChild>
          <Link href="/app/monitors/new">Add a hostname</Link>
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-xl leading-display text-ink">
          {monitors.total} monitored hostname{monitors.total === 1 ? "" : "s"}
        </h1>
        <Button asChild size="sm">
          <Link href="/app/monitors/new">Add hostname</Link>
        </Button>
      </div>
      <div className="overflow-x-auto rounded-card border border-line bg-surface">
        <table className="w-full min-w-[640px] text-left">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
              <th className="px-4 py-3 font-medium">Hostname</th>
              <th className="px-4 py-3 font-medium">Grade</th>
              <th className="px-4 py-3 font-medium">Expires in</th>
              <th className="px-4 py-3 font-medium">Last scanned</th>
              <th className="px-4 py-3 font-medium">State</th>
            </tr>
          </thead>
          <tbody>
            {monitors.items.map((monitor) => (
              <MonitorRow key={monitor.monitor_id} monitor={monitor} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
