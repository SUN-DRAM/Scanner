import Link from "next/link";

import { NewCampaignForm } from "@/components/admin/NewCampaignForm";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { listOutreachCampaigns } from "@/lib/api";
import { formatDateDisplay } from "@/lib/format";
import type { OutreachCampaignRow } from "@/types/contract";

export const dynamic = "force-dynamic";

const PER_PAGE = 50;

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function CampaignRow({ campaign }: { campaign: OutreachCampaignRow }) {
  const counts = campaign.state_counts;
  const inFlight = counts.scanning + counts.analyzing + counts.drafting;
  const readyForReview = counts.ready_for_review;
  return (
    <tr className="border-b border-line last:border-b-0 hover:bg-paper">
      <td className="px-4 py-3">
        <Link
          href={`/admin/outreach/${campaign.campaign_id}`}
          className="font-medium text-ink hover:underline"
        >
          {campaign.name}
        </Link>
        <p className="text-xs text-ink-muted">{formatDateDisplay(campaign.created_at)}</p>
      </td>
      <td className="px-4 py-3 text-sm capitalize text-ink-muted">{campaign.status}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{campaign.prospect_count}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{counts.pending}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{inFlight}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{readyForReview}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{counts.sent}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">{counts.replied}</td>
    </tr>
  );
}

export default async function AdminOutreachPage({ searchParams }: PageProps) {
  const token = await requireAdminToken();
  const sp = await searchParams;
  const pageParam = Array.isArray(sp.page) ? sp.page[0] : sp.page;
  const page = Math.max(1, Number.parseInt(pageParam ?? "1", 10) || 1);

  const data = await listOutreachCampaigns({ page, per_page: PER_PAGE }, token).catch((err) =>
    redirectIfForbidden(err),
  );

  return (
    <div>
      <h1 className="mb-6 font-display text-xl leading-display text-ink">Outreach</h1>

      <section className="mb-10 rounded-card border border-line bg-surface p-4">
        <h2 className="mb-1 font-display text-base leading-display text-ink">New campaign</h2>
        <p className="mb-4 text-sm text-ink-muted">
          Structured cold outreach for a qualified agency and its client domains. Internal GTM
          tooling — never customer-facing.
        </p>
        <NewCampaignForm />
      </section>

      <h2 className="mb-3 font-display text-base leading-display text-ink">
        {data.total} campaign{data.total === 1 ? "" : "s"}
      </h2>
      {data.total === 0 ? (
        <p className="rounded-card border border-line bg-surface px-6 py-12 text-center text-sm text-ink-muted">
          No campaigns yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full min-w-[820px] text-left">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-3 font-medium">Campaign</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Prospects</th>
                <th className="px-4 py-3 font-medium">Pending</th>
                <th className="px-4 py-3 font-medium">In flight</th>
                <th className="px-4 py-3 font-medium">Ready to review</th>
                <th className="px-4 py-3 font-medium">Sent</th>
                <th className="px-4 py-3 font-medium">Replied</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((campaign) => (
                <CampaignRow key={campaign.campaign_id} campaign={campaign} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
