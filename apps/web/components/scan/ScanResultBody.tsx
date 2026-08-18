import { Badge } from "@/components/ui/badge";
import { FindingRow } from "@/components/scan/FindingRow";
import { ModuleCard } from "@/components/scan/ModuleCard";
import { ValidityBar } from "@/components/scan/ValidityBar";
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

interface ScanResultBodyProps {
  scan: Scan;
}

/**
 * The validity bar, findings list, and module cards for a completed scan —
 * everything below a result page's own headline/grade, which differs
 * between where this is embedded (the public share page's centred hero vs.
 * the dashboard's compact monitor header). Shared here so changing how a
 * result renders only ever happens once (CLAUDE.md's Step 7 working
 * agreement: "reuse every Phase 1 component... do not fork it").
 */
export function ScanResultBody({ scan }: ScanResultBodyProps) {
  const certificate = scan.modules.certificate;
  const readiness = scan.modules.readiness;
  const scannedAt = scan.completed_at ?? scan.created_at;

  return (
    <>
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
    </>
  );
}
