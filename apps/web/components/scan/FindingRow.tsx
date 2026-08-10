import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { severityLabel, severityTone } from "@/lib/format";
import type { Finding } from "@/types/contract";

const SEVERITY_BADGE_VARIANT = {
  critical: "alert",
  high: "alert",
  medium: "warn",
  low: "neutral",
  info: "neutral",
} as const;

interface FindingRowProps {
  finding: Finding;
}

export function FindingRow({ finding }: FindingRowProps) {
  const tone = severityTone(finding.severity);
  const evidenceEntries = Object.entries(finding.evidence);

  return (
    <li className="border-b border-line py-4 last:border-b-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-3">
          <Badge variant={SEVERITY_BADGE_VARIANT[finding.severity]}>
            {severityLabel(finding.severity)}
          </Badge>
          <h3 className="font-display text-base leading-display text-ink">{finding.title}</h3>
        </div>
        <Link
          href={finding.docs_path}
          className="shrink-0 text-xs font-medium text-cobalt hover:underline"
        >
          Learn more
        </Link>
      </div>

      <p className="mt-2 text-sm leading-prose text-ink-muted">{finding.description}</p>
      <p className="mt-2 text-sm leading-prose text-ink">
        <span className="font-medium">Fix: </span>
        {finding.remediation}
      </p>

      {evidenceEntries.length > 0 ? (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-ink-muted">
          {evidenceEntries.map(([key, value]) => (
            <div key={key} className="flex gap-1.5">
              <dt className="text-ink-muted">{key}:</dt>
              <dd className={tone === "alert" ? "text-alert" : "text-ink"}>
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  );
}
