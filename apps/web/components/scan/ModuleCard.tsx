import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FindingRow } from "@/components/scan/FindingRow";
import { gradeTone } from "@/lib/format";
import type { ModuleResult } from "@/types/contract";

const STATUS_LABEL: Record<ModuleResult<unknown>["status"], string> = {
  ok: "Clean",
  warn: "Needs attention",
  fail: "Failing",
  error: "Could not complete",
  skipped: "Skipped",
};

const GRADE_BADGE_VARIANT = { pass: "pass", warn: "warn", alert: "alert" } as const;

interface ModuleCardProps {
  result: ModuleResult<unknown> | null;
}

export function ModuleCard({ result }: ModuleCardProps) {
  if (result === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Waiting…</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-ink-muted">This check hasn&apos;t reported back yet.</p>
        </CardContent>
      </Card>
    );
  }

  const hasNoData = result.status === "error" || result.status === "skipped";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{result.label}</CardTitle>
          {result.grade !== null ? (
            <Badge variant={GRADE_BADGE_VARIANT[gradeTone(result.grade)]}>{result.grade}</Badge>
          ) : (
            <Badge variant="neutral">{STATUS_LABEL[result.status]}</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-prose text-ink-muted">{result.summary}</p>

        {hasNoData && result.error !== null ? (
          <p className="mt-3 rounded-control bg-line/30 px-3 py-2 font-mono text-xs text-ink-muted">
            {result.error}
          </p>
        ) : null}

        {result.findings.length > 0 ? (
          <ul className="mt-4">
            {result.findings.map((finding) => (
              <FindingRow key={finding.code} finding={finding} />
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
