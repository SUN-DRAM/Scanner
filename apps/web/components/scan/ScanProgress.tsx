import { Check, Loader2, X } from "lucide-react";

import type { ModuleName, Modules, ScanStatus } from "@/types/contract";

// Display-only labels for the pending state, before a module's own
// backend-authored `label` has landed. Once a module result exists, its own
// `label` is used instead — these seven strings never appear on a
// completed report.
const MODULE_LABELS: Record<ModuleName, string> = {
  certificate: "Certificate",
  chain: "Certificate chain",
  tls: "TLS configuration",
  dns: "DNS & domain",
  email_auth: "Email authentication",
  headers: "Security headers",
  readiness: "2027 readiness",
};

const MODULE_ORDER: ModuleName[] = [
  "certificate",
  "chain",
  "tls",
  "dns",
  "email_auth",
  "headers",
  "readiness",
];

interface ScanProgressProps {
  status: ScanStatus;
  modules: Modules;
}

/** Shows progress per module as it lands rather than a bare spinner — the
 * scan takes seconds and the visitor should see it working (Step 7). */
export function ScanProgress({ status, modules }: ScanProgressProps) {
  return (
    <div className="mx-auto max-w-reading">
      <p className="mb-6 text-center font-display text-lg leading-display text-ink">
        {status === "queued" ? "Queued…" : "Scanning…"}
      </p>
      <ul className="flex flex-col gap-3">
        {MODULE_ORDER.map((name) => {
          const result = modules[name];
          const label = result?.label ?? MODULE_LABELS[name];
          const failed = result?.status === "error" || result?.status === "fail";

          return (
            <li
              key={name}
              className="flex items-center gap-3 rounded-control border border-line bg-surface px-4 py-3"
            >
              {result === null ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-ink-muted" />
              ) : failed ? (
                <X className="h-4 w-4 shrink-0 text-alert" />
              ) : (
                <Check className="h-4 w-4 shrink-0 text-pass" />
              )}
              <span className="text-sm text-ink">{label}</span>
              {result !== null ? (
                <span className="ml-auto font-mono text-xs text-ink-muted">
                  {result.duration_ms}ms
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
