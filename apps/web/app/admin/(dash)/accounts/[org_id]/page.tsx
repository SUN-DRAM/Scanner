import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { redirectIfForbidden, requireAdminToken } from "@/lib/admin-session";
import { ApiRequestError, getAdminAccount } from "@/lib/api";
import { formatDateDisplay, formatDateTimeDisplay, formatMoney, gradeTone } from "@/lib/format";
import type {
  AdminAlertRow,
  AdminScanRow,
  AlertState,
  AlertType,
  Grade,
  Invoice,
  InvoiceState,
  MembershipWithEmail,
  MonitoredHostname,
  MonitorState,
  PlanCode,
  Subscription,
  SubscriptionState,
  UserRole,
} from "@/types/contract";

export const dynamic = "force-dynamic";

const PLAN_LABEL: Record<PlanCode, string> = {
  free: "Free",
  watch: "Watch",
  watch_pro: "Watch Pro",
  secure: "Secure",
  compliance: "Compliance",
};

const ROLE_LABEL: Record<UserRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

const MONITOR_STATE_LABEL: Record<MonitorState, string> = {
  active: "Active",
  paused: "Paused",
  quota_blocked: "Over plan limit",
  verification_pending: "Verifying",
};

const ALERT_STATE_LABEL: Record<AlertState, string> = {
  pending: "Scheduled",
  sent: "Sent",
  failed: "Failed",
  suppressed: "Suppressed",
};

const ALERT_TYPE_LABEL: Record<AlertType, string> = {
  cert_expiry: "Certificate expiry",
  domain_expiry: "Domain expiry",
  grade_regression: "Grade regression",
  scan_failure: "Scan failure",
  new_critical_finding: "New critical finding",
};

const INVOICE_STATE_LABEL: Record<InvoiceState, string> = {
  open: "Open",
  paid: "Paid",
  void: "Void",
  uncollectible: "Uncollectible",
};

const SUBSCRIPTION_STATE_LABEL: Record<SubscriptionState, string> = {
  trialing: "Trialing",
  active: "Active",
  past_due: "Past due",
  cancelled: "Cancelled",
  expired: "Expired",
};

const GRADE_BADGE_VARIANT = { pass: "pass", warn: "warn", alert: "alert" } as const;

interface PageProps {
  params: Promise<{ org_id: string }>;
}

function GradeBadge({ grade }: { grade: Grade | null }) {
  if (grade === null) return <span className="text-ink-muted">—</span>;
  return <Badge variant={GRADE_BADGE_VARIANT[gradeTone(grade)]}>{grade}</Badge>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 font-display text-base leading-display text-ink">{title}</h2>
      {children}
    </section>
  );
}

function TableShell({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-card border border-line bg-surface">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
            {head}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function EmptyCard({ text }: { text: string }) {
  return (
    <p className="rounded-card border border-line bg-surface px-4 py-6 text-center text-sm text-ink-muted">
      {text}
    </p>
  );
}

function AlertRow({ alert }: { alert: AdminAlertRow }) {
  return (
    <tr className="border-b border-line align-top last:border-b-0">
      <td className="px-4 py-3 font-mono text-xs text-ink">{alert.monitor_hostname}</td>
      <td className="px-4 py-3 text-ink">{ALERT_TYPE_LABEL[alert.type]}</td>
      <td className="px-4 py-3">
        <span
          className={
            alert.state === "failed"
              ? "font-medium text-alert"
              : alert.state === "sent"
                ? "text-ink"
                : "text-ink-muted"
          }
        >
          {ALERT_STATE_LABEL[alert.state]}
        </span>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">
        {alert.recipients.length > 0 ? alert.recipients.join(", ") : "—"}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">
        {formatDateTimeDisplay(alert.sent_at ?? alert.scheduled_for)}
      </td>
    </tr>
  );
}

function InvoiceRow({ invoice }: { invoice: Invoice }) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-3 font-mono text-xs text-ink">{invoice.number}</td>
      <td className="px-4 py-3 font-mono text-sm text-ink">
        {formatMoney(invoice.amount_minor, invoice.currency)}
      </td>
      <td className="px-4 py-3 text-ink-muted">{INVOICE_STATE_LABEL[invoice.state]}</td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">
        {formatDateDisplay(invoice.issued_at)}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">{invoice.gstin ?? "—"}</td>
    </tr>
  );
}

function MonitorRow({ monitor }: { monitor: MonitoredHostname }) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-3 font-mono text-xs text-ink">
        {monitor.hostname}
        {monitor.port !== 443 ? `:${monitor.port}` : ""}
      </td>
      <td className="px-4 py-3 text-ink-muted">{MONITOR_STATE_LABEL[monitor.state]}</td>
      <td className="px-4 py-3">
        <GradeBadge grade={monitor.last_grade} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink">
        {monitor.days_until_expiry === null
          ? "—"
          : monitor.days_until_expiry < 0
            ? "Expired"
            : `${monitor.days_until_expiry}d`}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">
        {monitor.last_scanned_at ? formatDateDisplay(monitor.last_scanned_at) : "Not yet"}
      </td>
    </tr>
  );
}

function MemberRow({ member }: { member: MembershipWithEmail }) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-3 font-mono text-xs text-ink">{member.email}</td>
      <td className="px-4 py-3 text-ink-muted">{ROLE_LABEL[member.role]}</td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">
        {formatDateDisplay(member.joined_at)}
      </td>
    </tr>
  );
}

function ScanRow({ scan }: { scan: AdminScanRow }) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-3 font-mono text-xs text-ink">{scan.hostname}</td>
      <td className="px-4 py-3 text-ink-muted">{scan.status}</td>
      <td className="px-4 py-3">
        <GradeBadge grade={scan.grade} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-ink-muted">
        {formatDateTimeDisplay(scan.created_at)}
      </td>
      <td className="px-4 py-3">
        <a
          href={scan.share_url}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-xs text-ink underline hover:text-ink-muted"
        >
          {scan.public_slug}
        </a>
      </td>
    </tr>
  );
}

function SubscriptionCard({ subscription }: { subscription: Subscription }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-card border border-line bg-surface px-4 py-4 text-sm sm:grid-cols-3">
      <Field label="Plan" value={PLAN_LABEL[subscription.plan_code]} />
      <Field label="State" value={SUBSCRIPTION_STATE_LABEL[subscription.state]} />
      <Field label="Provider" value={subscription.provider} />
      <Field label="Interval" value={subscription.interval} />
      <Field
        label="Current period ends"
        value={formatDateDisplay(subscription.current_period_end)}
      />
      <Field
        label="Cancels at period end"
        value={subscription.cancel_at_period_end ? "Yes" : "No"}
      />
    </dl>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-ink">{value}</dd>
    </div>
  );
}

export default async function AdminAccountDetailPage({ params }: PageProps) {
  const token = await requireAdminToken();
  const { org_id } = await params;

  const detail = await getAdminAccount(org_id, token).catch((err) => {
    if (err instanceof ApiRequestError && err.code === "NOT_FOUND") notFound();
    return redirectIfForbidden(err);
  });

  const { org, members, subscription, invoices, monitors, failed_alerts, recent_alerts, recent_scans } =
    detail;

  return (
    <div>
      <Link
        href="/admin/accounts"
        className="text-sm text-ink-muted hover:text-ink hover:underline"
      >
        ← All accounts
      </Link>

      <div className="mb-8 mt-2 flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl leading-display text-ink">{org.name}</h1>
        <Badge>{PLAN_LABEL[org.plan_code]}</Badge>
        <span className="font-mono text-xs text-ink-muted">{org.org_id}</span>
      </div>

      {failed_alerts.length > 0 ? (
        <div className="mb-10 rounded-card border border-alert bg-alert/10 px-4 py-4">
          <p className="mb-3 font-display text-base leading-display text-alert">
            {failed_alerts.length} alert{failed_alerts.length === 1 ? "" : "s"} failed to
            deliver
          </p>
          <p className="mb-3 text-sm text-ink-muted">
            The customer believes they are covered for these and are not.
          </p>
          <div className="overflow-x-auto rounded-card border border-alert/40 bg-surface">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-3 font-medium">Hostname</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">State</th>
                  <th className="px-4 py-3 font-medium">Recipients</th>
                  <th className="px-4 py-3 font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {failed_alerts.map((alert) => (
                  <AlertRow key={alert.alert_id} alert={alert} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <Section title="Organisation">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-card border border-line bg-surface px-4 py-4 text-sm sm:grid-cols-3">
          <Field label="Country" value={org.country} />
          <Field label="Currency" value={org.currency} />
          <Field label="Timezone" value={org.timezone} />
          <Field
            label="Quiet hours"
            value={`${org.quiet_hours_start}–${org.quiet_hours_end}`}
          />
          <Field label="Digest" value={`${org.digest_mode} @ ${org.digest_hour}:00`} />
          <Field label="Created" value={formatDateDisplay(org.created_at)} />
        </dl>
      </Section>

      <Section title={`Members (${members.length})`}>
        {members.length === 0 ? (
          <EmptyCard text="No members." />
        ) : (
          <TableShell
            head={
              <>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Joined</th>
              </>
            }
          >
            {members.map((member) => (
              <MemberRow key={member.user_id} member={member} />
            ))}
          </TableShell>
        )}
      </Section>

      <Section title={`Monitored hostnames (${monitors.length})`}>
        {monitors.length === 0 ? (
          <EmptyCard text="No hostnames monitored." />
        ) : (
          <TableShell
            head={
              <>
                <th className="px-4 py-3 font-medium">Hostname</th>
                <th className="px-4 py-3 font-medium">State</th>
                <th className="px-4 py-3 font-medium">Grade</th>
                <th className="px-4 py-3 font-medium">Expires in</th>
                <th className="px-4 py-3 font-medium">Last scanned</th>
              </>
            }
          >
            {monitors.map((monitor) => (
              <MonitorRow key={monitor.monitor_id} monitor={monitor} />
            ))}
          </TableShell>
        )}
      </Section>

      <Section title="Subscription & invoices">
        {subscription ? (
          <SubscriptionCard subscription={subscription} />
        ) : (
          <EmptyCard text="No subscription — on the free plan." />
        )}
        {invoices.length > 0 ? (
          <div className="mt-4">
            <TableShell
              head={
                <>
                  <th className="px-4 py-3 font-medium">Number</th>
                  <th className="px-4 py-3 font-medium">Amount</th>
                  <th className="px-4 py-3 font-medium">State</th>
                  <th className="px-4 py-3 font-medium">Issued</th>
                  <th className="px-4 py-3 font-medium">GSTIN</th>
                </>
              }
            >
              {invoices.map((invoice) => (
                <InvoiceRow key={invoice.invoice_id} invoice={invoice} />
              ))}
            </TableShell>
          </div>
        ) : null}
      </Section>

      <Section title="Alert delivery">
        {recent_alerts.length === 0 ? (
          <EmptyCard text="No alerts have fired for this account." />
        ) : (
          <TableShell
            head={
              <>
                <th className="px-4 py-3 font-medium">Hostname</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">State</th>
                <th className="px-4 py-3 font-medium">Recipients</th>
                <th className="px-4 py-3 font-medium">When</th>
              </>
            }
          >
            {recent_alerts.map((alert) => (
              <AlertRow key={alert.alert_id} alert={alert} />
            ))}
          </TableShell>
        )}
      </Section>

      <Section title="Recent scans">
        {recent_scans.length === 0 ? (
          <EmptyCard text="No scans yet." />
        ) : (
          <TableShell
            head={
              <>
                <th className="px-4 py-3 font-medium">Hostname</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Grade</th>
                <th className="px-4 py-3 font-medium">When</th>
                <th className="px-4 py-3 font-medium">Link</th>
              </>
            }
          >
            {recent_scans.map((scan) => (
              <ScanRow key={scan.scan_id} scan={scan} />
            ))}
          </TableShell>
        )}
      </Section>
    </div>
  );
}
