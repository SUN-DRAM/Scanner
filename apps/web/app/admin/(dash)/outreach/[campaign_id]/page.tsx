import Link from "next/link";
import { notFound } from "next/navigation";

import { ImportCsvForm } from "@/components/admin/ImportCsvForm";
import { ProspectStateFilter } from "@/components/admin/ProspectStateFilter";
import { ScanProgressPanel } from "@/components/admin/ScanProgressPanel";
import { Badge } from "@/components/ui/badge";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { ApiRequestError, getOutreachCampaign, listOutreachProspects } from "@/lib/api";
import { formatDateDisplay } from "@/lib/format";
import type { OutreachProspectRow, OutreachProspectState } from "@/types/contract";

export const dynamic = "force-dynamic";

const PER_PAGE = 50;

const STATE_BADGE_VARIANT: Record<OutreachProspectState, "neutral" | "pass" | "warn" | "alert"> = {
  pending: "neutral",
  scanning: "neutral",
  analyzing: "neutral",
  suppressed: "neutral",
  drafting: "neutral",
  ready_for_review: "warn",
  sent: "pass",
  replied: "pass",
  failed: "alert",
  skipped: "neutral",
};

interface PageProps {
  params: Promise<{ campaign_id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function ProspectRow({ prospect }: { prospect: OutreachProspectRow }) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-3">
        <p className="font-medium text-ink">{prospect.agency_name}</p>
        <p className="text-xs text-ink-muted">{prospect.contact_email}</p>
      </td>
      <td className="px-4 py-3 text-sm text-ink-muted">{prospect.contact_name ?? "—"}</td>
      <td className="px-4 py-3">
        <Badge variant={STATE_BADGE_VARIANT[prospect.state]}>{prospect.state}</Badge>
        {prospect.state_reason ? (
          <p className="mt-1 text-xs text-ink-muted">{prospect.state_reason}</p>
        ) : null}
      </td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{prospect.domain_count}</td>
      <td className="px-4 py-3 text-sm text-ink-muted">
        {formatDateDisplay(prospect.created_at)}
      </td>
    </tr>
  );
}

export default async function AdminOutreachCampaignPage({ params, searchParams }: PageProps) {
  const token = await requireAdminToken();
  const { campaign_id } = await params;
  const sp = await searchParams;

  const campaign = await getOutreachCampaign(campaign_id, token).catch((err) => {
    if (err instanceof ApiRequestError && err.code === "NOT_FOUND") notFound();
    return redirectIfForbidden(err);
  });

  const page = Math.max(1, Number.parseInt(one(sp.page) ?? "1", 10) || 1);
  const state = one(sp.state) as OutreachProspectState | undefined;

  const prospects = await listOutreachProspects(
    campaign_id,
    { page, per_page: PER_PAGE, state },
    token,
  ).catch((err) => redirectIfForbidden(err));

  return (
    <div>
      <Link
        href="/admin/outreach"
        className="text-sm text-ink-muted hover:text-ink hover:underline"
      >
        ← All campaigns
      </Link>

      <div className="mb-6 mt-2">
        <h1 className="font-display text-xl leading-display text-ink">{campaign.name}</h1>
        <p className="text-sm text-ink-muted">
          {formatDateDisplay(campaign.created_at)} · {campaign.status} ·{" "}
          {campaign.prospect_count} prospect{campaign.prospect_count === 1 ? "" : "s"}
        </p>
      </div>

      <section className="mb-10 rounded-card border border-line bg-surface p-4">
        <h2 className="mb-1 font-display text-base leading-display text-ink">Import CSV</h2>
        <p className="mb-4 text-sm text-ink-muted">
          One row per (agency, client domain). Re-importing the same file changes nothing.
        </p>
        <ImportCsvForm campaignId={campaign_id} />
      </section>

      <ScanProgressPanel campaignId={campaign_id} initialStatus={campaign.status} />

      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <h2 className="font-display text-base leading-display text-ink">
          {prospects.total} prospect{prospects.total === 1 ? "" : "s"}
        </h2>
        <ProspectStateFilter />
      </div>

      {prospects.total === 0 ? (
        <p className="rounded-card border border-line bg-surface px-6 py-12 text-center text-sm text-ink-muted">
          No prospects match these filters.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-3 font-medium">Agency</th>
                <th className="px-4 py-3 font-medium">Contact</th>
                <th className="px-4 py-3 font-medium">State</th>
                <th className="px-4 py-3 font-medium">Domains</th>
                <th className="px-4 py-3 font-medium">Imported</th>
              </tr>
            </thead>
            <tbody>
              {prospects.items.map((prospect) => (
                <ProspectRow key={prospect.prospect_id} prospect={prospect} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
