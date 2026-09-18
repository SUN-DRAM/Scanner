"use client";

import { useEffect, useState, useTransition } from "react";

import { getScanProgress, pauseScan, resumeScan, startScan } from "@/app/admin/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  OutreachCampaignStatus,
  OutreachDomainState,
  OutreachScanProgress,
} from "@/types/contract";

// "Poll the progress endpoint; no websockets" (stage prompt's own words).
// Well under OUTREACH_SCAN_DELAY_SECONDS' 15s default, so a claim or a
// settlement is visible on the next poll, not the next page load.
const POLL_INTERVAL_MS = 4000;

const DOMAIN_STATE_ORDER: OutreachDomainState[] = [
  "pending",
  "running",
  "retrying",
  "completed",
  "completed_partial",
  "failed",
];

const DOMAIN_STATE_LABELS: Record<OutreachDomainState, string> = {
  pending: "Pending",
  running: "Running",
  retrying: "Retrying",
  completed: "Completed",
  completed_partial: "Partial",
  failed: "Failed",
};

const OUTCOME_BADGE_VARIANT: Record<string, "pass" | "warn" | "alert"> = {
  completed: "pass",
  completed_partial: "warn",
  failed: "alert",
};

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="font-mono text-sm text-ink">{value}</p>
    </div>
  );
}

export function ScanProgressPanel({
  campaignId,
  initialStatus,
}: {
  campaignId: string;
  initialStatus: OutreachCampaignStatus;
}) {
  const [progress, setProgress] = useState<OutreachScanProgress | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [includeWeak, setIncludeWeak] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      const result = await getScanProgress(campaignId);
      if (cancelled) return;
      if (result) {
        setProgress(result);
        setRefreshFailed(false);
      } else {
        setRefreshFailed(true);
      }
    }

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [campaignId]);

  const status = progress?.campaign_status ?? initialStatus;

  function handleStart() {
    setError(null);
    startTransition(async () => {
      const result = await startScan(campaignId, includeWeak);
      if (!result.ok) setError(result.error);
    });
  }

  function handlePause() {
    setError(null);
    startTransition(async () => {
      const result = await pauseScan(campaignId);
      if (!result.ok) setError(result.error);
    });
  }

  function handleResume() {
    setError(null);
    startTransition(async () => {
      const result = await resumeScan(campaignId);
      if (!result.ok) setError(result.error);
    });
  }

  return (
    <section className="mb-10 rounded-card border border-line bg-surface p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-base leading-display text-ink">Scan</h2>
          <p className="text-sm text-ink-muted">
            Status: <span className="font-medium capitalize text-ink">{status}</span>
            {refreshFailed ? " · couldn't refresh just now" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {status === "draft" ? (
            <>
              <label className="flex items-center gap-2 text-sm text-ink-muted">
                <input
                  type="checkbox"
                  checked={includeWeak}
                  onChange={(event) => setIncludeWeak(event.target.checked)}
                  disabled={pending}
                />
                Include weak-graded prospects
              </label>
              <Button onClick={handleStart} disabled={pending}>
                {pending ? "Starting" : "Start scan"}
              </Button>
            </>
          ) : null}
          {status === "running" ? (
            <Button variant="secondary" onClick={handlePause} disabled={pending}>
              {pending ? "Pausing" : "Pause"}
            </Button>
          ) : null}
          {status === "paused" ? (
            <Button onClick={handleResume} disabled={pending}>
              {pending ? "Resuming" : "Resume"}
            </Button>
          ) : null}
        </div>
      </div>

      {error ? (
        <p role="alert" className="mb-3 text-sm text-alert">
          {error}
        </p>
      ) : null}

      {progress === null ? (
        <p className="text-sm text-ink-muted">Loading progress…</p>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
            {DOMAIN_STATE_ORDER.map((state) => (
              <div
                key={state}
                className="rounded-control border border-line bg-paper px-2 py-2 text-center"
              >
                <p className="text-xs uppercase tracking-wide text-ink-muted">
                  {DOMAIN_STATE_LABELS[state]}
                </p>
                <p className="font-mono text-lg text-ink">{progress.domain_state_counts[state]}</p>
              </div>
            ))}
          </div>

          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="In flight" value={String(progress.in_flight)} />
            <Stat label="Started" value={formatTime(progress.started_at)} />
            <Stat
              label="Est. completion"
              value={
                progress.estimated_completion_at
                  ? formatTime(progress.estimated_completion_at)
                  : "Not enough data yet"
              }
            />
            <Stat label="Wall time" value={formatDuration(progress.metrics.total_wall_time_ms)} />
          </div>

          <div className="mb-4 rounded-control border border-line bg-paper p-3">
            <h3 className="mb-2 text-xs uppercase tracking-wide text-ink-muted">Batch metrics</h3>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Stat
                label="Clean rate"
                value={
                  progress.metrics.clean_rate !== null
                    ? `${Math.round(progress.metrics.clean_rate * 100)}%`
                    : "—"
                }
              />
              <Stat
                label="Median duration"
                value={formatDuration(progress.metrics.median_scan_duration_ms)}
              />
              <Stat
                label="P95 duration"
                value={formatDuration(progress.metrics.p95_scan_duration_ms)}
              />
              <Stat
                label="Completed partial"
                value={String(progress.metrics.completed_partial_count)}
              />
              <Stat label="Failed" value={String(progress.metrics.failed_count)} />
              <Stat
                label="Retried & rescued"
                value={String(progress.metrics.retried_and_rescued_count)}
              />
            </div>
            {Object.keys(progress.metrics.completed_partial_by_module_error).length > 0 ? (
              <p className="mt-3 text-xs text-ink-muted">
                Partial reasons:{" "}
                {Object.entries(progress.metrics.completed_partial_by_module_error)
                  .map(([code, count]) => `${code} (${count})`)
                  .join(", ")}
              </p>
            ) : null}
            {Object.keys(progress.metrics.failed_by_reason).length > 0 ? (
              <p className="mt-1 text-xs text-ink-muted">
                Failure reasons:{" "}
                {Object.entries(progress.metrics.failed_by_reason)
                  .map(([reason, count]) => `${reason} (${count})`)
                  .join("; ")}
              </p>
            ) : null}
          </div>

          <div>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-ink-muted">
              Recent outcomes
            </h3>
            {progress.recent_outcomes.length === 0 ? (
              <p className="text-sm text-ink-muted">Nothing settled yet.</p>
            ) : (
              <ul className="divide-y divide-line rounded-control border border-line bg-paper text-sm">
                {progress.recent_outcomes.map((outcome) => (
                  <li
                    key={outcome.domain_id}
                    className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                  >
                    <span>
                      <span className="font-mono text-ink">{outcome.hostname}</span>
                      <span className="text-ink-muted"> — {outcome.agency_name}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge variant={OUTCOME_BADGE_VARIANT[outcome.state] ?? "neutral"}>
                        {outcome.state}
                      </Badge>
                      <span className="text-xs text-ink-muted">
                        {formatTime(outcome.settled_at)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
