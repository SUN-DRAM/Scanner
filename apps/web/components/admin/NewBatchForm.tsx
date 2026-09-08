"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProspectBatch } from "@/app/admin/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const TEXTAREA_CLASS =
  "min-h-[140px] w-full rounded-control border border-line bg-surface p-3 font-mono text-sm text-ink placeholder:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink";

export function NewBatchForm() {
  const router = useRouter();
  const [label, setLabel] = useState("");
  const [hostnames, setHostnames] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createProspectBatch(label, hostnames);
      if (result.ok) {
        router.push(`/admin/prospects/${result.batchId}`);
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
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-ink-muted">
        Label
        <Input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Redwing Agency portfolio"
          disabled={submitting}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-ink-muted">
        Hostnames
        <textarea
          className={TEXTAREA_CLASS}
          value={hostnames}
          onChange={(event) => setHostnames(event.target.value)}
          placeholder={"one per line, or comma-separated\nexample.com\nwww.example.com:8443"}
          disabled={submitting}
        />
      </label>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? "Scanning" : "Scan batch"}
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
