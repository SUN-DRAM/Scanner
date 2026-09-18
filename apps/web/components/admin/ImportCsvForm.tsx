"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { importOutreachCsv } from "@/app/admin/actions";
import { Button } from "@/components/ui/button";
import type { OutreachImportReport } from "@/types/contract";

/** Plain rendering of the §17.5 import report — nothing imports silently,
 * so every count and every rejected or suppressed row is shown here. */
function ImportReportView({ report }: { report: OutreachImportReport }) {
  return (
    <div className="mt-4 rounded-card border border-line bg-paper p-4 text-sm text-ink">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-muted">Imported</dt>
          <dd className="font-mono">
            {report.imported_agencies} agencies, {report.imported_domains} domains
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-muted">Skipped</dt>
          <dd className="font-mono">{report.skipped_agencies} agencies</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-muted">Suppressed</dt>
          <dd className="font-mono">{report.suppressed_agencies} agencies</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-muted">Rejected rows</dt>
          <dd className="font-mono">{report.rejected_rows.length}</dd>
        </div>
      </dl>

      {report.rejected_rows.length > 0 ? (
        <div className="mt-4">
          <h3 className="mb-1 text-xs uppercase tracking-wide text-ink-muted">Rejected rows</h3>
          <ul className="space-y-1 font-mono text-xs text-alert">
            {report.rejected_rows.map((row) => (
              <li key={row.row_number}>
                Row {row.row_number}: {row.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.warnings.length > 0 ? (
        <div className="mt-4">
          <h3 className="mb-1 text-xs uppercase tracking-wide text-ink-muted">Warnings</h3>
          <ul className="space-y-1 font-mono text-xs text-warn">
            {report.warnings.map((warning, index) => (
              <li key={`${warning.contact_email}-${index}`}>
                {warning.contact_email}: {warning.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function ImportCsvForm({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<OutreachImportReport | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(formData: FormData) {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    setReport(null);
    try {
      const result = await importOutreachCsv(campaignId, formData);
      if (result.ok) {
        setReport(result.report);
        formRef.current?.reset();
        router.refresh();
      } else {
        setError(result.error);
      }
    } catch {
      setError("Could not reach the API. Try again.");
    }
    setSubmitting(false);
  }

  return (
    <div>
      <form ref={formRef} action={handleSubmit} className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          name="file"
          accept=".csv,text/csv"
          required
          disabled={submitting}
          className="text-sm text-ink file:mr-3 file:rounded-control file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:bg-paper"
        />
        <Button type="submit" disabled={submitting}>
          {submitting ? "Importing" : "Import CSV"}
        </Button>
        {error ? (
          <p role="alert" className="text-sm text-alert">
            {error}
          </p>
        ) : null}
      </form>
      {report ? <ImportReportView report={report} /> : null}
    </div>
  );
}
