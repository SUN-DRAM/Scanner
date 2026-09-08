import { Sparkline } from "@/components/admin/Sparkline";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { getAdminFunnel } from "@/lib/api";
import { formatDateTimeDisplay } from "@/lib/format";
import type { AdminFunnelRates, AdminFunnelSeries } from "@/types/contract";

export const dynamic = "force-dynamic";

const SERIES: { key: keyof AdminFunnelSeries; label: string; hint: string }[] = [
  { key: "scans_total", label: "Scans per day", hint: "Every scan the engine ran." },
  {
    key: "scans_anonymous",
    label: "Anonymous scans",
    hint: "Run from the public scan box — no account attached.",
  },
  {
    key: "scans_logged_in",
    label: "Logged-in scans",
    hint: "Run on behalf of an account's monitored hostname.",
  },
  {
    key: "unique_hostnames",
    label: "Unique hostnames scanned",
    hint: "Distinct hostnames per day.",
  },
  { key: "waitlist_signups", label: "Waitlist signups", hint: "Email captured against a scan." },
];

const RATES: { key: keyof AdminFunnelRates; label: string }[] = [
  { key: "scan_to_waitlist", label: "Scan → waitlist" },
  { key: "waitlist_to_account", label: "Waitlist → account" },
  { key: "account_to_activation", label: "Account → first hostname" },
  { key: "account_to_paid", label: "Account → paid" },
];

function ratePercent(value: number | null): string {
  if (value === null) return "unknown";
  return `${(value * 100).toFixed(1)}%`;
}

export default async function AdminFunnelPage() {
  const token = await requireAdminToken();
  const funnel = await getAdminFunnel(token).catch((err) => redirectIfForbidden(err));

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="font-display text-xl leading-display text-ink">Funnel</h1>
        <p className="text-sm text-ink-muted">
          Last {funnel.days} days · generated {formatDateTimeDisplay(funnel.generated_at)}
        </p>
      </div>

      <section className="mb-10">
        <h2 className="mb-3 font-display text-base leading-display text-ink">
          Conversion, whole window
        </h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {RATES.map((rate) => (
            <div key={rate.key} className="rounded-card border border-line bg-surface px-4 py-3">
              <p className="text-xs uppercase tracking-wide text-ink-muted">{rate.label}</p>
              <p className="mt-1 font-display text-2xl leading-display text-ink">
                {ratePercent(funnel.rates[rate.key])}
              </p>
            </div>
          ))}
        </div>
      </section>

      {SERIES.map((series) => (
        <section key={series.key} className="mb-8">
          <h2 className="font-display text-base leading-display text-ink">{series.label}</h2>
          <p className="mb-2 text-sm text-ink-muted">{series.hint}</p>
          <div className="rounded-card border border-line bg-surface px-4 py-3">
            <Sparkline points={funnel.series[series.key]} />
          </div>
        </section>
      ))}
    </div>
  );
}
