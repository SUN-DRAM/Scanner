import type { Metadata } from "next";

import { BillingPanel } from "@/components/app/BillingPanel";
import {
  ApiRequestError,
  getBillingPlans,
  getCurrentOrg,
  getSubscription,
  listInvoices,
  listMembers,
  listMonitors,
} from "@/lib/api";
import { getForwardedCookie } from "@/lib/session";

export const metadata: Metadata = { title: "Billing" };

export default async function BillingPage() {
  const cookie = await getForwardedCookie();

  try {
    const [org, plans, subscription, invoices, monitors] = await Promise.all([
      getCurrentOrg(cookie),
      getBillingPlans(cookie),
      getSubscription(cookie),
      listInvoices({ per_page: 25 }, cookie),
      listMonitors({ per_page: 1 }, cookie),
    ]);

    return (
      <div>
        <h1 className="mb-6 font-display text-xl leading-display text-ink">Billing</h1>
        <BillingPanel
          org={org}
          plans={plans.plans}
          subscription={subscription}
          invoices={invoices.items}
          hostnamesInUse={monitors.total}
        />
      </div>
    );
  } catch (err) {
    if (err instanceof ApiRequestError && err.code === "FORBIDDEN") {
      const members = await listMembers({ per_page: 100 }, cookie);
      const owners = members.items.filter((member) => member.role === "owner");
      return (
        <div className="rounded-card border border-line bg-surface px-6 py-16 text-center">
          <h1 className="mb-2 font-display text-xl leading-display text-ink">
            Only the org owner can manage billing
          </h1>
          <p className="text-sm text-ink-muted">
            {owners.length > 0
              ? `Ask ${owners.map((owner) => owner.email).join(" or ")} to make changes here.`
              : "Ask your organisation's owner to make changes here."}
          </p>
        </div>
      );
    }
    throw err;
  }
}
