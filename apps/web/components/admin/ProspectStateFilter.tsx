"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import type { OutreachProspectState } from "@/types/contract";

const STATES: { value: OutreachProspectState | ""; label: string }[] = [
  { value: "", label: "All states" },
  { value: "pending", label: "Pending" },
  { value: "scanning", label: "Scanning" },
  { value: "analyzing", label: "Analyzing" },
  { value: "suppressed", label: "Suppressed" },
  { value: "drafting", label: "Drafting" },
  { value: "ready_for_review", label: "Ready for review" },
  { value: "sent", label: "Sent" },
  { value: "replied", label: "Replied" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
];

const SELECT_CLASS =
  "h-9 rounded-control border border-line bg-surface px-2 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink";

export function ProspectStateFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const setState = useCallback(
    (value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) {
        next.set("state", value);
      } else {
        next.delete("state");
      }
      next.delete("page");
      router.push(`${pathname}?${next.toString()}`);
    },
    [params, pathname, router],
  );

  return (
    <label className="flex flex-col gap-1 text-xs text-ink-muted">
      State
      <select
        className={SELECT_CLASS}
        value={params.get("state") ?? ""}
        onChange={(event) => setState(event.target.value)}
      >
        {STATES.map((option) => (
          <option key={option.label} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
