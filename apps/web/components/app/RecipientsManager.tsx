"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, createRecipient, deleteRecipient } from "@/lib/api";
import type { AlertRecipient } from "@/types/contract";

interface MonitorOption {
  monitor_id: string;
  hostname: string;
}

interface RecipientsManagerProps {
  initialRecipients: AlertRecipient[];
  monitors: MonitorOption[];
}

const ORG_WIDE_VALUE = "";

export function RecipientsManager({ initialRecipients, monitors }: RecipientsManagerProps) {
  const [recipients, setRecipients] = useState(initialRecipients);
  const [email, setEmail] = useState("");
  const [monitorId, setMonitorId] = useState(ORG_WIDE_VALUE);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const hostnameById = new Map(monitors.map((monitor) => [monitor.monitor_id, monitor.hostname]));

  async function handleAdd(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const recipient = await createRecipient({
        email: trimmed,
        monitor_id: monitorId === ORG_WIDE_VALUE ? null : monitorId,
      });
      setRecipients((current) => {
        const withoutDuplicate = current.filter((row) => row.recipient_id !== recipient.recipient_id);
        return [...withoutDuplicate, recipient];
      });
      setEmail("");
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not reach the scanner. Check your connection and try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(recipientId: string) {
    setDeletingId(recipientId);
    setError(null);
    try {
      await deleteRecipient(recipientId);
      setRecipients((current) => current.filter((row) => row.recipient_id !== recipientId));
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not reach the scanner. Check your connection and try again.",
      );
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="flex max-w-reading flex-col gap-4">
      {recipients.length > 0 ? (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {recipients.map((recipient) => (
            <li key={recipient.recipient_id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div>
                <p className="text-sm text-ink">{recipient.email}</p>
                <p className="text-xs text-ink-muted">
                  {recipient.monitor_id
                    ? (hostnameById.get(recipient.monitor_id) ?? "One hostname")
                    : "All monitors"}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {!recipient.verified ? <Badge variant="neutral">Unverified</Badge> : null}
                <button
                  type="button"
                  onClick={() => handleDelete(recipient.recipient_id)}
                  disabled={deletingId === recipient.recipient_id}
                  className="text-xs font-medium text-ink-muted hover:text-alert hover:underline"
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-muted">
          No recipients yet — alerts currently go to every owner and admin&apos;s own email.
        </p>
      )}

      <form onSubmit={handleAdd} className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="ops@yourcompany.com"
          aria-label="Recipient email"
          className="sm:flex-1"
        />
        <select
          value={monitorId}
          onChange={(event) => setMonitorId(event.target.value)}
          aria-label="Scope"
          className="h-12 rounded-control border border-line bg-surface px-4 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cobalt"
        >
          <option value={ORG_WIDE_VALUE}>All monitors</option>
          {monitors.map((monitor) => (
            <option key={monitor.monitor_id} value={monitor.monitor_id}>
              {monitor.hostname}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={submitting || email.trim().length === 0}>
          {submitting ? "Adding" : "Add"}
        </Button>
      </form>
      {error ? (
        <p role="alert" className="text-sm text-alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
