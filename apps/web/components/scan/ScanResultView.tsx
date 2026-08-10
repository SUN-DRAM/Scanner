"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { FindingRow } from "@/components/scan/FindingRow";
import { GradeDial } from "@/components/scan/GradeDial";
import { ModuleCard } from "@/components/scan/ModuleCard";
import { ScanProgress } from "@/components/scan/ScanProgress";
import { ValidityBar } from "@/components/scan/ValidityBar";
import { pollScan, ScanPollTimeoutError } from "@/lib/api";
import { formatDateTimeDisplay } from "@/lib/format";
import type { ModuleName, Scan } from "@/types/contract";

const MODULE_ORDER: ModuleName[] = [
  "certificate",
  "chain",
  "tls",
  "dns",
  "email_auth",
  "headers",
  "readiness",
];

interface ScanResultViewProps {
  initialScan: Scan;
}

export function ScanResultView({ initialScan }: ScanResultViewProps) {
  const [scan, setScan] = useState(initialScan);
  const [pollTimedOut, setPollTimedOut] = useState(false);

  useEffect(() => {
    if (scan.status !== "queued" && scan.status !== "running") return;

    const controller = new AbortController();
    pollScan(scan.scan_id, { onUpdate: setScan, signal: controller.signal }).catch((err) => {
      if (err instanceof ScanPollTimeoutError) {
        setScan(err.lastScan);
        setPollTimedOut(true);
      }
    });

    return () => controller.abort();
    // Only re-subscribes if the scan being tracked changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan.scan_id]);

  if (scan.status === "queued" || scan.status === "running") {
    return (
      <main className="mx-auto max-w-content px-4 py-16">
        <ScanProgress status={scan.status} modules={scan.modules} />
        {pollTimedOut ? (
          <p className="mt-6 text-center text-sm text-ink-muted">
            This is taking longer than expected. Refresh the page to check again.
          </p>
        ) : null}
      </main>
    );
  }

  if (scan.status === "failed") {
    return (
      <main className="mx-auto flex max-w-reading flex-col items-center gap-4 px-4 py-24 text-center">
        <h1 className="font-display text-2xl leading-display text-ink">
          Scan didn&apos;t complete
        </h1>
        <p className="text-ink-muted">{scan.error?.message ?? "The scan failed. Try again."}</p>
        <Link href="/" className="font-medium text-cobalt hover:underline">
          Start a new scan
        </Link>
      </main>
    );
  }

  const certificate = scan.modules.certificate;
  const readiness = scan.modules.readiness;
  const scannedAt = scan.completed_at ?? scan.created_at;

  return (
    <main className="mx-auto max-w-content px-4 py-12">
      <section className="flex flex-col items-center gap-4 border-b border-line pb-10 text-center">
        <p className="font-mono text-sm text-ink-muted">{scan.hostname}</p>
        {scan.overall_grade !== null && scan.overall_score !== null ? (
          <GradeDial grade={scan.overall_grade} score={scan.overall_score} />
        ) : null}
        <h1 className="max-w-reading font-display text-xl leading-display text-ink sm:text-2xl">
          {scan.headline}
        </h1>
        <p className="font-mono text-xs text-ink-muted">
          Scanned {formatDateTimeDisplay(scannedAt)}
        </p>
      </section>

      {certificate?.data ? (
        <section className="border-b border-line py-10">
          <h2 className="mb-4 font-display text-lg text-ink">Certificate validity</h2>
          <ValidityBar
            notBefore={certificate.data.not_before}
            notAfter={certificate.data.not_after}
            now={scannedAt}
            survives2027={readiness?.data?.survives_2027 ?? null}
          />
        </section>
      ) : null}

      <section className="border-b border-line py-10">
        <h2 className="mb-4 font-display text-lg text-ink">Findings ({scan.findings.length})</h2>
        {scan.findings.length > 0 ? (
          <ul>
            {scan.findings.map((finding) => (
              <FindingRow key={`${finding.module}-${finding.code}`} finding={finding} />
            ))}
          </ul>
        ) : (
          <div className="flex items-center gap-3">
            <Badge variant="pass">Clean result</Badge>
            <p className="text-ink-muted">Nothing to fix.</p>
          </div>
        )}
      </section>

      <section className="py-10">
        <h2 className="mb-4 font-display text-lg text-ink">Every check</h2>
        {/* `sm` is the contract's 360px floor — two columns of card content
            needs `md` (768px) to not cramp. */}
        <div className="grid gap-4 md:grid-cols-2">
          {MODULE_ORDER.map((name) => (
            <ModuleCard key={name} result={scan.modules[name]} />
          ))}
        </div>
      </section>
    </main>
  );
}
