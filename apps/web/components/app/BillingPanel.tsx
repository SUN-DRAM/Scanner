"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiRequestError, cancelSubscription, createCheckout } from "@/lib/api";
import { formatDateDisplay, formatMoney } from "@/lib/format";
import type {
  BillingInterval,
  Invoice,
  Organisation,
  PlanCode,
  PricedPlan,
  Subscription,
} from "@/types/contract";

interface BillingPanelProps {
  org: Organisation;
  plans: PricedPlan[];
  subscription: Subscription | null;
  invoices: Invoice[];
  hostnamesInUse: number;
}

const INVOICE_STATE_LABEL: Record<Invoice["state"], string> = {
  open: "Open",
  paid: "Paid",
  void: "Void",
  uncollectible: "Uncollectible",
};

function PlanCard({
  plan,
  currentPlanCode,
  onCheckout,
  checkingOut,
}: {
  plan: PricedPlan;
  currentPlanCode: PlanCode;
  onCheckout: (planCode: PlanCode, interval: BillingInterval) => void;
  checkingOut: boolean;
}) {
  const isCurrent = plan.plan_code === currentPlanCode;

  return (
    <div className="flex flex-col gap-3 rounded-card border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg text-ink">{plan.plan_code}</h3>
        {isCurrent ? <Badge variant="cobalt">Current plan</Badge> : null}
      </div>
      {plan.purchasable ? (
        <>
          <p className="font-mono text-sm text-ink">
            {formatMoney(plan.monthly_amount_minor ?? 0, plan.currency)}/mo
            <span className="text-ink-muted"> or </span>
            {formatMoney(plan.annual_amount_minor ?? 0, plan.currency)}/yr
          </p>
          <ul className="text-sm text-ink-muted">
            <li>{plan.hostname_limit} hostnames</li>
            <li>{plan.member_limit} team members</li>
            <li>Re-scans every {plan.scan_interval_hours}h</li>
          </ul>
          {!isCurrent ? (
            <div className="mt-2 flex gap-2">
              <Button
                size="sm"
                disabled={checkingOut}
                onClick={() => onCheckout(plan.plan_code, "monthly")}
              >
                Upgrade monthly
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={checkingOut}
                onClick={() => onCheckout(plan.plan_code, "annual")}
              >
                Upgrade yearly
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-ink-muted">Contact us for pricing.</p>
      )}
    </div>
  );
}

export function BillingPanel({ org, plans, subscription, invoices, hostnamesInUse }: BillingPanelProps) {
  const [checkingOut, setCheckingOut] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentPlan = plans.find((plan) => plan.plan_code === org.plan_code);

  async function handleCheckout(planCode: PlanCode, interval: BillingInterval) {
    setCheckingOut(true);
    setError(null);
    try {
      const response = await createCheckout({ plan_code: planCode, interval });
      if (response.contact_us) {
        setError("This plan isn't self-serve yet — contact us to set it up.");
        return;
      }
      if (response.checkout_url) {
        window.location.href = response.checkout_url;
      }
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not start checkout.");
    } finally {
      setCheckingOut(false);
    }
  }

  async function handleCancel() {
    if (!window.confirm("Cancel your subscription at the end of the current period?")) return;
    setCancelling(true);
    setError(null);
    try {
      await cancelSubscription();
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not cancel your subscription.");
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="flex flex-col gap-10">
      <section className="rounded-card border border-line bg-surface p-6">
        <p className="text-sm text-ink-muted">Current usage</p>
        <p className="mt-1 font-display text-lg text-ink">
          {hostnamesInUse}
          {currentPlan?.hostname_limit !== undefined && currentPlan.hostname_limit !== null
            ? ` of ${currentPlan.hostname_limit}`
            : ""}{" "}
          hostnames monitored
        </p>
        {subscription ? (
          <div className="mt-4 border-t border-line pt-4 text-sm text-ink-muted">
            <p>
              Subscription <span className="text-ink">{subscription.state}</span> via{" "}
              {subscription.provider}, renews {formatDateDisplay(subscription.current_period_end)}
              {subscription.cancel_at_period_end ? " (cancelling at period end)" : ""}.
            </p>
            {!subscription.cancel_at_period_end ? (
              <Button size="sm" variant="ghost" className="mt-2" onClick={handleCancel} disabled={cancelling}>
                {cancelling ? "Cancelling…" : "Cancel subscription"}
              </Button>
            ) : null}
          </div>
        ) : null}
        {error ? (
          <p role="alert" className="mt-3 text-sm text-alert">
            {error}
          </p>
        ) : null}
      </section>

      <section>
        <h2 className="mb-4 font-display text-lg text-ink">Plans</h2>
        <div className="grid gap-4 md:grid-cols-2">
          {plans.map((plan) => (
            <PlanCard
              key={plan.plan_code}
              plan={plan}
              currentPlanCode={org.plan_code}
              onCheckout={handleCheckout}
              checkingOut={checkingOut}
            />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-4 font-display text-lg text-ink">Invoices</h2>
        {invoices.length > 0 ? (
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {invoices.map((invoice) => (
              <li key={invoice.invoice_id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                <span className="font-mono text-ink-muted">{invoice.number}</span>
                <span className="text-ink">{formatMoney(invoice.amount_minor, invoice.currency)}</span>
                <span className="text-ink-muted">{INVOICE_STATE_LABEL[invoice.state]}</span>
                <span className="font-mono text-xs text-ink-muted">
                  {formatDateDisplay(invoice.issued_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-muted">No invoices yet.</p>
        )}
      </section>
    </div>
  );
}
