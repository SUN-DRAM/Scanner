import type { Metadata } from "next";

import { AddMonitorForm } from "@/components/app/AddMonitorForm";

export const metadata: Metadata = { title: "Add a hostname" };

export default function NewMonitorPage() {
  return (
    <div className="mx-auto max-w-reading">
      <h1 className="mb-2 font-display text-xl leading-display text-ink">Add a hostname</h1>
      <p className="mb-8 text-sm text-ink-muted">
        We&apos;ll scan it now, then keep re-scanning it on your plan&apos;s schedule and email you
        before anything expires.
      </p>
      <AddMonitorForm />
    </div>
  );
}
