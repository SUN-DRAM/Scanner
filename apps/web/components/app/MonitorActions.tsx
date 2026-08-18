"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ApiRequestError, deleteMonitor, triggerManualScan, updateMonitor } from "@/lib/api";
import type { MonitorState } from "@/types/contract";

interface MonitorActionsProps {
  monitorId: string;
  hostname: string;
  state: MonitorState;
}

/** Trigger re-scan, pause/resume, delete — the row-level actions §7.8
 * already exposes as endpoints; this is the client-side wiring for the
 * monitor detail page. Every action re-fetches the (Server Component) page
 * afterward via `router.refresh()` rather than tracking server state here
 * a second time. */
export function MonitorActions({ monitorId, hostname, state }: MonitorActionsProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<"scan" | "toggle" | "delete" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function handleScanNow() {
    setBusy("scan");
    setMessage(null);
    try {
      await triggerManualScan(monitorId);
      router.refresh();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleTogglePause() {
    setBusy("toggle");
    setMessage(null);
    try {
      await updateMonitor(monitorId, { state: state === "active" ? "paused" : "active" });
      router.refresh();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Stop monitoring ${hostname}? This can't be undone.`)) return;
    setBusy("delete");
    setMessage(null);
    try {
      await deleteMonitor(monitorId);
      router.push("/app");
      router.refresh();
    } catch (err) {
      setMessage(errorMessage(err));
      setBusy(null);
    }
  }

  const canToggle = state === "active" || state === "paused";

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={handleScanNow} disabled={busy !== null}>
          {busy === "scan" ? "Scanning…" : "Scan now"}
        </Button>
        {canToggle ? (
          <Button size="sm" variant="secondary" onClick={handleTogglePause} disabled={busy !== null}>
            {state === "active" ? "Pause" : "Resume"}
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" onClick={handleDelete} disabled={busy !== null}>
          {busy === "delete" ? "Removing…" : "Remove"}
        </Button>
      </div>
      {message ? (
        <p role="alert" className="text-sm text-alert">
          {message}
        </p>
      ) : null}
    </div>
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) return err.message;
  return "Could not reach the scanner. Check your connection and try again.";
}
