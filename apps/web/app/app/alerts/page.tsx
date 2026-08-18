import type { Metadata } from "next";

import { QuietHoursForm } from "@/components/app/QuietHoursForm";
import { RecipientsManager } from "@/components/app/RecipientsManager";
import { getCurrentOrg, listMonitors, listRecipients } from "@/lib/api";
import { getForwardedCookie } from "@/lib/session";

export const metadata: Metadata = { title: "Alerts" };

export default async function AlertsPage() {
  const cookie = await getForwardedCookie();
  const [org, recipients, monitors] = await Promise.all([
    getCurrentOrg(cookie),
    listRecipients({ per_page: 100 }, cookie),
    listMonitors({ per_page: 100 }, cookie),
  ]);

  return (
    <div className="flex flex-col gap-10">
      <section>
        <h1 className="mb-2 font-display text-xl leading-display text-ink">Alert settings</h1>
        <p className="mb-6 text-sm text-ink-muted">
          Choose who hears about a problem, and when we&apos;re allowed to interrupt them.
        </p>
        <QuietHoursForm org={org} />
      </section>

      <section>
        <h2 className="mb-2 font-display text-lg text-ink">Recipients</h2>
        <p className="mb-4 text-sm text-ink-muted">
          Consider a shared address like <span className="font-mono">ops@yourcompany.com</span>{" "}
          instead of a personal one — it keeps working after someone leaves the team.
        </p>
        <RecipientsManager
          initialRecipients={recipients.items}
          monitors={monitors.items.map((monitor) => ({
            monitor_id: monitor.monitor_id,
            hostname: monitor.hostname,
          }))}
        />
      </section>
    </div>
  );
}
