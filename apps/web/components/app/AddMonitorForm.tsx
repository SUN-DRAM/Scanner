"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, bulkCreateMonitors, createMonitor } from "@/lib/api";
import type { MonitorBulkRow, PlanCode } from "@/types/contract";

type Mode = "single" | "bulk";

interface QuotaDetails {
  current: number;
  limit: number;
  plan_code: PlanCode;
  upgrade_to: PlanCode | null;
}

function isQuotaDetails(details: unknown): details is QuotaDetails {
  return (
    typeof details === "object" &&
    details !== null &&
    "limit" in details &&
    "plan_code" in details
  );
}

/** The empty-state instruction that matters most (§Step 7): "a free user at
 * 3 of 3 sees the upgrade path without a modal interrupting them" — this
 * banner, inline in the same form, reading the QUOTA_EXCEEDED payload
 * (§7.8) rather than a hardcoded limit anywhere on this page. */
function QuotaBanner({ details }: { details: QuotaDetails }) {
  return (
    <div className="rounded-card border border-line bg-cobalt-soft p-4 text-sm text-ink">
      <p>
        You&apos;ve reached your <span className="font-medium">{details.plan_code}</span> plan
        &apos;s limit of {details.limit} hostnames ({details.current} in use).
      </p>
      {details.upgrade_to ? (
        <Link href="/app/billing" className="mt-2 inline-block font-medium text-cobalt hover:underline">
          Upgrade to {details.upgrade_to} →
        </Link>
      ) : (
        <p className="mt-2 text-ink-muted">Contact us to discuss a higher limit.</p>
      )}
    </div>
  );
}

export function AddMonitorForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("single");

  const [hostname, setHostname] = useState("");
  const [label, setLabel] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<QuotaDetails | null>(null);

  const [bulkText, setBulkText] = useState("");
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const [bulkResults, setBulkResults] = useState<MonitorBulkRow[] | null>(null);
  const [bulkQuota, setBulkQuota] = useState<QuotaDetails | null>(null);

  async function handleSingleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = hostname.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    setQuota(null);
    try {
      const monitor = await createMonitor({
        hostname: trimmed,
        port: null,
        label: label.trim() || null,
        notes: null,
      });
      router.push(`/app/monitors/${monitor.monitor_id}`);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiRequestError) {
        if (err.code === "QUOTA_EXCEEDED" && isQuotaDetails(err.details)) {
          setQuota(err.details);
          return;
        }
        setError(err.message);
      } else {
        setError("Could not reach the scanner. Check your connection and try again.");
      }
    }
  }

  async function handleBulkSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const hostnames = bulkText
      .split(/[\n,]/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (hostnames.length === 0 || bulkSubmitting) return;

    setBulkSubmitting(true);
    setBulkResults(null);
    setBulkQuota(null);
    try {
      const response = await bulkCreateMonitors({ hostnames });
      setBulkResults(response.results);
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === "QUOTA_EXCEEDED" && isQuotaDetails(err.details)) {
        setBulkQuota(err.details);
      }
    } finally {
      setBulkSubmitting(false);
    }
  }

  return (
    <div>
      <div className="mb-6 inline-flex rounded-control border border-line bg-surface p-1">
        {(["single", "bulk"] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setMode(option)}
            className={`rounded-control px-4 py-1.5 text-sm font-medium transition-colors ${
              mode === option ? "bg-cobalt-soft text-cobalt" : "text-ink-muted hover:text-ink"
            }`}
          >
            {option === "single" ? "Add one" : "Bulk paste"}
          </button>
        ))}
      </div>

      {mode === "single" ? (
        <form onSubmit={handleSingleSubmit} className="flex flex-col gap-4">
          <Input
            value={hostname}
            onChange={(event) => setHostname(event.target.value)}
            placeholder="example.com"
            aria-label="Hostname to monitor"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={submitting}
          />
          <Input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="Label (optional) — e.g. Production"
            aria-label="Label"
            disabled={submitting}
          />
          <Button type="submit" disabled={submitting || hostname.trim().length === 0}>
            {submitting ? "Adding" : "Add hostname"}
          </Button>
          {quota ? <QuotaBanner details={quota} /> : null}
          {error ? (
            <p role="alert" className="text-sm text-alert">
              {error}
            </p>
          ) : null}
        </form>
      ) : (
        <form onSubmit={handleBulkSubmit} className="flex flex-col gap-4">
          <textarea
            value={bulkText}
            onChange={(event) => setBulkText(event.target.value)}
            placeholder={"example.com\napi.example.com\nexample.org"}
            aria-label="Hostnames to monitor, one per line"
            rows={8}
            disabled={bulkSubmitting}
            className="w-full rounded-control border border-line bg-surface px-4 py-3 font-mono text-sm text-ink placeholder:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cobalt"
          />
          <p className="text-xs text-ink-muted">One per line (or comma-separated), up to 100.</p>
          <Button type="submit" disabled={bulkSubmitting || bulkText.trim().length === 0}>
            {bulkSubmitting ? "Adding" : "Add hostnames"}
          </Button>
          {bulkQuota ? <QuotaBanner details={bulkQuota} /> : null}
          {bulkResults ? (
            <ul className="divide-y divide-line rounded-card border border-line bg-surface">
              {bulkResults.map((row) => (
                <li key={row.hostname} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span className="font-mono text-ink">{row.hostname}</span>
                  {row.accepted ? (
                    <span className="text-pass">Added</span>
                  ) : (
                    <span className="text-right text-alert">{row.reason}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </form>
      )}
    </div>
  );
}
