import type { Metadata } from "next";

import { Badge } from "@/components/ui/badge";
import { getHealth, type HealthStatus } from "@/lib/api";
import { formatDateTimeDisplay } from "@/lib/format";

export const metadata: Metadata = {
  title: "API status",
  description: "Live status of the SUN-DRAM Scanner API.",
  alternates: { canonical: "/api-status" },
};

const DEPENDENCY_LABEL: Record<string, string> = {
  database: "Database",
  redis: "Redis",
};

export default async function ApiStatusPage() {
  let health: HealthStatus | null = null;
  let unreachable = false;

  try {
    health = await getHealth();
  } catch {
    unreachable = true;
  }

  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <h1 className="font-display text-2xl leading-display text-ink">API status</h1>

      {unreachable || !health ? (
        <p className="mt-6 text-alert">
          The API did not respond. If this persists, the scanner is temporarily unavailable.
        </p>
      ) : (
        <div className="mt-6 flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <Badge variant={health.status === "ok" ? "pass" : "alert"}>
              {health.status === "ok" ? "Operational" : "Degraded"}
            </Badge>
            <span className="font-mono text-xs text-ink-muted">version {health.version}</span>
          </div>

          <dl className="divide-y divide-line rounded-card border border-line bg-surface">
            {(["database", "redis"] as const).map((key) => (
              <div key={key} className="flex items-center justify-between px-4 py-3">
                <dt className="text-sm text-ink">{DEPENDENCY_LABEL[key]}</dt>
                <dd>
                  <Badge variant={health[key] === "ok" ? "pass" : "alert"}>{health[key]}</Badge>
                </dd>
              </div>
            ))}
          </dl>

          <p className="font-mono text-xs text-ink-muted">
            Checked {formatDateTimeDisplay(health.checked_at)}
          </p>
        </div>
      )}
    </main>
  );
}
