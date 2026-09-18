"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createCampaign } from "@/app/admin/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function NewCampaignForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createCampaign(name);
      if (result.ok) {
        router.push(`/admin/outreach/${result.campaignId}`);
        router.refresh();
        return;
      }
      setError(result.error);
    } catch {
      setError("Could not reach the API. Try again.");
    }
    setSubmitting(false);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <label className="flex flex-1 flex-col gap-1 text-xs uppercase tracking-wide text-ink-muted">
        Campaign name
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Clutch agencies — Sept batch"
          disabled={submitting}
        />
      </label>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? "Creating" : "New campaign"}
        </Button>
        {error ? (
          <p role="alert" className="text-sm text-alert">
            {error}
          </p>
        ) : null}
      </div>
    </form>
  );
}
