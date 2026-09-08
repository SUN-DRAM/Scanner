import Link from "next/link";

import { AccountFilters } from "@/components/admin/AccountFilters";
import { Badge } from "@/components/ui/badge";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { listAdminAccounts, type ListAdminAccountsParams } from "@/lib/api";
import { formatDateDisplay, gradeTone } from "@/lib/format";
import type {
  AccountHealth,
  AdminAccountRow,
  AdminAccountSort,
  Grade,
  PlanCode,
} from "@/types/contract";

export const dynamic = "force-dynamic";

const PER_PAGE = 50;

const PLAN_LABEL: Record<PlanCode, string> = {
  free: "Free",
  watch: "Watch",
  watch_pro: "Watch Pro",
  secure: "Secure",
  compliance: "Compliance",
};

const HEALTH_LABEL: Record<AccountHealth, string> = {
  activated: "Activated",
  stalled: "Stalled",
  at_risk: "At risk",
  dormant: "Dormant",
};

// Monochrome by design (§12 grade colours are the only fixed palette here).
// `stalled` is filled dark — it's the list the operator works from.
const HEALTH_CLASS: Record<AccountHealth, string> = {
  activated: "bg-line/40 text-ink-muted",
  stalled: "bg-ink text-surface",
  at_risk: "border border-warn text-warn",
  dormant: "border border-alert text-alert",
};

const GRADE_BADGE_VARIANT = { pass: "pass", warn: "warn", alert: "alert" } as const;

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function GradeBadge({ grade }: { grade: Grade | null }) {
  if (grade === null) return <span className="text-ink-muted">—</span>;
  return <Badge variant={GRADE_BADGE_VARIANT[gradeTone(grade)]}>{grade}</Badge>;
}

function expiryLabel(row: AdminAccountRow): string {
  if (row.soonest_expiry_days === null || row.soonest_expiry_at === null) return "—";
  const day = formatDateDisplay(row.soonest_expiry_at);
  if (row.soonest_expiry_days < 0) return `Expired · ${day}`;
  if (row.soonest_expiry_days === 0) return `Today · ${day}`;
  return `${row.soonest_expiry_days}d · ${day}`;
}

function AccountRow({ row }: { row: AdminAccountRow }) {
  return (
    <tr className="border-b border-line align-top last:border-b-0 hover:bg-paper">
      <td className="px-4 py-3">
        <Link href={`/admin/accounts/${row.org_id}`} className="font-medium text-ink hover:underline">
          {row.name}
        </Link>
        <p className="font-mono text-xs text-ink-muted">{row.primary_email}</p>
      </td>
      <td className="px-4 py-3 text-sm text-ink-muted">{row.signed_up_relative}</td>
      <td className="px-4 py-3 text-sm text-ink">
        {PLAN_LABEL[row.plan_code]}
        {row.is_paying ? (
          <span className="ml-1 align-top text-xs text-ink-muted">· paying</span>
        ) : null}
      </td>
      <td className="px-4 py-3 font-mono text-sm text-ink">
        {row.hostname_count}
        <span className="text-ink-muted">
          /{row.hostname_limit ?? "—"}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-ink-muted">
        {row.last_login_relative ?? "never"}
      </td>
      <td className="px-4 py-3 text-sm text-ink-muted">
        {row.last_scan_at ? formatDateDisplay(row.last_scan_at) : "—"}
      </td>
      <td className="px-4 py-3">
        <GradeBadge grade={row.worst_grade} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink">{expiryLabel(row)}</td>
      <td className="px-4 py-3 text-sm text-ink-muted">{row.alerts_sent_count}</td>
      <td className="px-4 py-3">
        <span
          className={`inline-flex items-center rounded-control px-2.5 py-1 text-xs font-medium ${HEALTH_CLASS[row.health]}`}
        >
          {HEALTH_LABEL[row.health]}
        </span>
      </td>
    </tr>
  );
}

export default async function AdminAccountsPage({ searchParams }: PageProps) {
  const token = await requireAdminToken();
  const sp = await searchParams;

  const page = Math.max(1, Number.parseInt(one(sp.page) ?? "1", 10) || 1);
  const params: ListAdminAccountsParams = {
    page,
    per_page: PER_PAGE,
    plan: one(sp.plan) as PlanCode | undefined,
    health: one(sp.health) as AccountHealth | undefined,
    sort: (one(sp.sort) as AdminAccountSort | undefined) ?? "newest",
    signed_up_after: one(sp.signed_up_after),
    signed_up_before: one(sp.signed_up_before),
  };

  const data = await listAdminAccounts(params, token).catch((err) =>
    redirectIfForbidden(err),
  );

  const buildPageHref = (target: number) => {
    const next = new URLSearchParams();
    for (const [key, value] of Object.entries(sp)) {
      const v = one(value);
      if (v) next.set(key, v);
    }
    next.set("page", String(target));
    return `/admin/accounts?${next.toString()}`;
  };

  const rangeStart = data.total === 0 ? 0 : (page - 1) * PER_PAGE + 1;
  const rangeEnd = Math.min(page * PER_PAGE, data.total);

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="font-display text-xl leading-display text-ink">Accounts</h1>
        <p className="text-sm text-ink-muted">
          {data.total} organisation{data.total === 1 ? "" : "s"}
        </p>
      </div>

      <AccountFilters />

      {data.total === 0 ? (
        <p className="rounded-card border border-line bg-surface px-6 py-16 text-center text-sm text-ink-muted">
          No accounts match these filters.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-card border border-line bg-surface">
            <table className="w-full min-w-[900px] text-left">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-3 font-medium">Org / email</th>
                  <th className="px-4 py-3 font-medium">Signed up</th>
                  <th className="px-4 py-3 font-medium">Plan</th>
                  <th className="px-4 py-3 font-medium">Hostnames</th>
                  <th className="px-4 py-3 font-medium">Last login</th>
                  <th className="px-4 py-3 font-medium">Last scan</th>
                  <th className="px-4 py-3 font-medium">Worst grade</th>
                  <th className="px-4 py-3 font-medium">Soonest expiry</th>
                  <th className="px-4 py-3 font-medium">Alerts sent</th>
                  <th className="px-4 py-3 font-medium">Health</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <AccountRow key={row.org_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between text-sm text-ink-muted">
            <span>
              {rangeStart}–{rangeEnd} of {data.total}
            </span>
            <span className="flex gap-2">
              {page > 1 ? (
                <Link
                  href={buildPageHref(page - 1)}
                  className="rounded-control border border-line px-3 py-1.5 font-medium text-ink hover:bg-paper"
                >
                  Previous
                </Link>
              ) : null}
              {data.has_more ? (
                <Link
                  href={buildPageHref(page + 1)}
                  className="rounded-control border border-line px-3 py-1.5 font-medium text-ink hover:bg-paper"
                >
                  Next
                </Link>
              ) : null}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
