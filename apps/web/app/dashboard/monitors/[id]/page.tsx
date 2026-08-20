import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { GradeHistorySparkline } from "@/components/app/GradeHistorySparkline";
import { MonitorActions } from "@/components/app/MonitorActions";
import { ScanProgress } from "@/components/scan/ScanProgress";
import { ScanResultBody } from "@/components/scan/ScanResultBody";
import {
  ApiRequestError,
  getMonitor,
  getMonitorAlerts,
  getMonitorHistory,
  getScan,
} from "@/lib/api";
import { formatDateTimeDisplay } from "@/lib/format";
import { getForwardedCookie } from "@/lib/session";
import type { AlertEvent, AlertState, MonitorState, Severity } from "@/types/contract";

interface MonitorDetailPageProps {
  params: Promise<{ id: string }>;
}

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

const ALERT_STATE_LABEL: Record<AlertState, string> = {
  pending: "Scheduled",
  sent: "Sent",
  failed: "Failed",
  suppressed: "Suppressed",
};

const SEVERITY_VARIANT: Record<Severity, "alert" | "warn" | "neutral"> = {
  critical: "alert",
  high: "alert",
  medium: "warn",
  low: "neutral",
  info: "neutral",
};

export async function generateMetadata({ params }: MonitorDetailPageProps): Promise<Metadata> {
  const { id } = await params;
  const cookie = await getForwardedCookie();
  try {
    const monitor = await getMonitor(id, cookie);
    return { title: monitor.hostname };
  } catch {
    return { title: "Monitor" };
  }
}

function AlertLogRow({ event }: { event: AlertEvent }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-b border-line py-3 last:border-b-0">
      <div className="flex items-center gap-3">
        <Badge variant={SEVERITY_VARIANT[event.severity]}>{event.severity}</Badge>
        <span className="text-sm text-ink">{event.subject}</span>
      </div>
      <div className="flex items-center gap-3 text-xs text-ink-muted">
        <span>{ALERT_STATE_LABEL[event.state]}</span>
        <span className="font-mono">
          {formatDateTimeDisplay(event.sent_at ?? event.scheduled_for)}
        </span>
      </div>
    </li>
  );
}

export default async function MonitorDetailPage({ params }: MonitorDetailPageProps) {
  const { id } = await params;
  const cookie = await getForwardedCookie();

  const monitor = await getMonitor(id, cookie).catch((err) => {
    if (err instanceof ApiRequestError && err.code === "NOT_FOUND") notFound();
    throw err;
  });

  const [history, alerts, scan] = await Promise.all([
    getMonitorHistory(id, { per_page: 30 }, cookie),
    getMonitorAlerts(id, { per_page: 20 }, cookie),
    // Scan results are public/unauthenticated (Phase 1) — no cookie needed.
    monitor.last_scan_id ? getScan(monitor.last_scan_id) : Promise.resolve(null),
  ]);

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4 border-b border-line pb-8">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-mono text-xl text-ink">
              {monitor.hostname}
              {monitor.port !== 443 ? `:${monitor.port}` : ""}
            </h1>
            <Badge variant={STATE_VARIANT[monitor.state]}>{STATE_LABEL[monitor.state]}</Badge>
          </div>
          {monitor.label ? <p className="mt-1 text-sm text-ink-muted">{monitor.label}</p> : null}
        </div>
        <MonitorActions monitorId={monitor.monitor_id} hostname={monitor.hostname} state={monitor.state} />
      </div>

      <section className="mb-10 border-b border-line pb-10">
        <h2 className="mb-4 font-display text-lg text-ink">Grade history</h2>
        <GradeHistorySparkline entries={history.items} />
      </section>

      <section className="mb-10 border-b border-line pb-10">
        <h2 className="mb-4 font-display text-lg text-ink">Alert log</h2>
        {alerts.items.length > 0 ? (
          <ul>
            {alerts.items.map((event) => (
              <AlertLogRow key={event.alert_id} event={event} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-muted">No alerts fired for this hostname yet.</p>
        )}
      </section>

      <section>
        <h2 className="mb-4 font-display text-lg text-ink">Latest result</h2>
        {scan === null ? (
          <p className="text-sm text-ink-muted">
            Waiting for the first scan. This usually happens within a few minutes of adding a
            hostname.
          </p>
        ) : scan.status === "queued" || scan.status === "running" ? (
          <ScanProgress status={scan.status} modules={scan.modules} />
        ) : scan.status === "failed" ? (
          <p className="text-sm text-alert">
            {scan.error?.message ?? "The last scan failed. It will retry automatically."}
          </p>
        ) : (
          <ScanResultBody scan={scan} />
        )}
      </section>
    </div>
  );
}
