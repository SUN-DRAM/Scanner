"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, inviteMember, removeMember } from "@/lib/api";
import { formatDateDisplay } from "@/lib/format";
import type { MembershipWithEmail, UserRole } from "@/types/contract";

interface TeamManagerProps {
  initialMembers: MembershipWithEmail[];
  currentUserId: string;
}

const ROLE_OPTIONS: UserRole[] = ["member", "admin", "owner"];

export function TeamManager({ initialMembers, currentUserId }: TeamManagerProps) {
  const [members, setMembers] = useState(initialMembers);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("member");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  async function handleInvite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const membership = await inviteMember({ email: trimmed, role });
      setMembers((current) => {
        const withoutDuplicate = current.filter((row) => row.user_id !== membership.user_id);
        return [...withoutDuplicate, membership];
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

  async function handleRemove(userId: string) {
    setRemovingId(userId);
    setError(null);
    try {
      await removeMember(userId);
      setMembers((current) => current.filter((row) => row.user_id !== userId));
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not reach the scanner. Check your connection and try again.",
      );
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div className="flex max-w-reading flex-col gap-4">
      <ul className="divide-y divide-line rounded-card border border-line bg-surface">
        {members.map((member) => (
          <li key={member.user_id} className="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <p className="text-sm text-ink">
                {member.email}
                {member.user_id === currentUserId ? (
                  <span className="ml-2 text-xs text-ink-muted">(you)</span>
                ) : null}
              </p>
              <p className="text-xs text-ink-muted">Joined {formatDateDisplay(member.joined_at)}</p>
            </div>
            <div className="flex items-center gap-3">
              <Badge variant={member.role === "owner" ? "cobalt" : "neutral"}>{member.role}</Badge>
              <button
                type="button"
                onClick={() => handleRemove(member.user_id)}
                disabled={removingId === member.user_id}
                className="text-xs font-medium text-ink-muted hover:text-alert hover:underline"
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>

      <form onSubmit={handleInvite} className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="teammate@company.com"
          aria-label="Email to invite"
          className="sm:flex-1"
        />
        <select
          value={role}
          onChange={(event) => setRole(event.target.value as UserRole)}
          aria-label="Role"
          className="h-12 rounded-control border border-line bg-surface px-4 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cobalt"
        >
          {ROLE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={submitting || email.trim().length === 0}>
          {submitting ? "Inviting" : "Invite"}
        </Button>
      </form>
      <p className="text-xs text-ink-muted">
        They&apos;ll sign in with an email code, same as you — no separate invite link to send.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
