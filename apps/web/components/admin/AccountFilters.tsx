"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import type { AccountHealth, AdminAccountSort, PlanCode } from "@/types/contract";

const PLANS: { value: PlanCode | ""; label: string }[] = [
  { value: "", label: "All plans" },
  { value: "free", label: "Free" },
  { value: "watch", label: "Watch" },
  { value: "watch_pro", label: "Watch Pro" },
];

const HEALTH: { value: AccountHealth | ""; label: string }[] = [
  { value: "", label: "All health" },
  { value: "stalled", label: "Stalled" },
  { value: "activated", label: "Activated" },
  { value: "at_risk", label: "At risk" },
  { value: "dormant", label: "Dormant" },
];

const SORTS: { value: AdminAccountSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "last_login", label: "Last login" },
  { value: "soonest_expiry", label: "Soonest expiry" },
];

const SELECT_CLASS =
  "h-9 rounded-control border border-line bg-surface px-2 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink";

export function AccountFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const setParam = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
      // Any filter change resets to page 1 — page 3 of the old filter is
      // meaningless under the new one.
      next.delete("page");
      router.push(`${pathname}?${next.toString()}`);
    },
    [params, pathname, router],
  );

  return (
    <div className="mb-6 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-ink-muted">
        Plan
        <select
          className={SELECT_CLASS}
          value={params.get("plan") ?? ""}
          onChange={(event) => setParam("plan", event.target.value)}
        >
          {PLANS.map((option) => (
            <option key={option.label} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-ink-muted">
        Health
        <select
          className={SELECT_CLASS}
          value={params.get("health") ?? ""}
          onChange={(event) => setParam("health", event.target.value)}
        >
          {HEALTH.map((option) => (
            <option key={option.label} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-ink-muted">
        Sort
        <select
          className={SELECT_CLASS}
          value={params.get("sort") ?? "newest"}
          onChange={(event) => setParam("sort", event.target.value)}
        >
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-ink-muted">
        Signed up after
        <input
          type="date"
          className={SELECT_CLASS}
          value={params.get("signed_up_after") ?? ""}
          onChange={(event) => setParam("signed_up_after", event.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-ink-muted">
        Signed up before
        <input
          type="date"
          className={SELECT_CLASS}
          value={params.get("signed_up_before") ?? ""}
          onChange={(event) => setParam("signed_up_before", event.target.value)}
        />
      </label>
    </div>
  );
}
