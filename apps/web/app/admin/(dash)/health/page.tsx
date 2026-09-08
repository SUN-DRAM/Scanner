import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { getAdminHealth } from "@/lib/api";
import { formatDateTimeDisplay } from "@/lib/format";
import type { AdminHealthReport } from "@/types/contract";

export const dynamic = "force-dynamic";

function Stat({
  label,
  value,
  tone = "ink",
}: {
  label: string;
  value: string | number;
  tone?: "ink" | "warn" | "alert" | "muted";
}) {
  const toneClass =
    tone === "alert"
      ? "text-alert"
      : tone === "warn"
        ? "text-warn"
        : tone === "muted"
          ? "text-ink-muted"
          : "text-ink";
  return (
    <div className="rounded-card border border-line bg-surface px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className={`mt-1 font-display text-2xl leading-display ${toneClass}`}>{value}</p>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 font-display text-base leading-display text-ink">{title}</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">{children}</div>
    </section>
  );
}

function OverdueBanner({ report }: { report: AdminHealthReport }) {
  const n = report.scheduler.monitors_overdue_1h;
  if (n === 0) return null;
  return (
    <div className="mb-8 rounded-card border border-alert bg-alert/10 px-4 py-3">
      <p className="font-display text-lg leading-display text-alert">
        {n} monitor{n === 1 ? "" : "s"} overdue by more than an hour
      </p>
      <p className="mt-1 text-sm text-ink-muted">
        The scheduler is not keeping up, or has stopped. Customers hear nothing when
        this happens.
      </p>
    </div>
  );
}

export default async function AdminHealthPage() {
  const token = await requireAdminToken();
  const report = await getAdminHealth(token).catch((err) => redirectIfForbidden(err));

  const dependencyTone = (status: "ok" | "error") => (status === "ok" ? "ink" : "alert");

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="font-display text-xl leading-display text-ink">Health</h1>
        <p className="text-sm text-ink-muted">
          Generated {formatDateTimeDisplay(report.generated_at)}
        </p>
      </div>

      <OverdueBanner report={report} />

      <Panel title="Scheduler">
        <Stat
          label="Overdue > 1h"
          value={report.scheduler.monitors_overdue_1h}
          tone={report.scheduler.monitors_overdue_1h > 0 ? "alert" : "ink"}
        />
        <Stat
          label="Overdue"
          value={report.scheduler.monitors_overdue}
          tone={report.scheduler.monitors_overdue > 0 ? "warn" : "ink"}
        />
        <Stat label="Due now" value={report.scheduler.monitors_due} tone="muted" />
        <div className="col-span-2 rounded-card border border-line bg-surface px-4 py-3 md:col-span-3 lg:col-span-2">
          <p className="text-xs uppercase tracking-wide text-ink-muted">
            Last successful run
          </p>
          <p className="mt-1 font-mono text-sm text-ink">
            {report.scheduler.last_successful_run_at
              ? formatDateTimeDisplay(report.scheduler.last_successful_run_at)
              : "unknown"}
          </p>
        </div>
      </Panel>

      <Panel title="Scans, last 24h">
        <Stat label="Completed" value={report.scans_24h.completed} tone="muted" />
        <Stat
          label="Failed"
          value={report.scans_24h.failed}
          tone={report.scans_24h.failed > 0 ? "warn" : "ink"}
        />
        <Stat label="Queued" value={report.scans_24h.queued} tone="muted" />
        <Stat label="Running" value={report.scans_24h.running} tone="muted" />
        <Stat
          label="Stuck"
          value={report.scans_24h.stuck}
          tone={report.scans_24h.stuck > 0 ? "alert" : "ink"}
        />
      </Panel>

      <Panel title="Alert queue">
        <Stat label="Pending" value={report.alert_queue.pending} tone="muted" />
        <Stat
          label="Failed, 24h"
          value={report.alert_queue.failed_24h}
          tone={report.alert_queue.failed_24h > 0 ? "alert" : "ink"}
        />
        <Stat label="Worker queue depth" value={report.worker.queue_depth} tone="muted" />
        <Stat
          label="Worker memory"
          value={
            report.worker.memory_mb === null ? "unknown" : `${report.worker.memory_mb} MB`
          }
          tone="muted"
        />
      </Panel>

      <Panel title="Dependencies">
        <Stat
          label="Postgres"
          value={report.postgres}
          tone={dependencyTone(report.postgres)}
        />
        <Stat label="Redis" value={report.redis} tone={dependencyTone(report.redis)} />
      </Panel>
    </div>
  );
}
