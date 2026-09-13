import type { ModuleErrorCode, ModuleName, Modules } from "@/types/contract";

// docs/Fix headers and incomplete.md §4.1: a short, mid-sentence clause per
// code — deliberately not the full ModuleError.message (that already names
// the module and an exact duration, which would read redundant spliced into
// "...did not complete: security headers — The security headers check timed
// out after 3 seconds."). UNEXPECTED_ERROR has no entry: it isn't specific
// enough to be worth appending ("append the reason where we have one").
// Mirrors app/pdf/template.py's own copy of this table — same duplication
// pattern as gradeTone()/_GRADE_TONE for a small, closed, enum-driven set.
const REASON_PHRASE: Partial<Record<ModuleErrorCode, string>> = {
  MODULE_TIMEOUT: "the check timed out",
  CONNECTION_REFUSED: "the connection was refused",
  CONNECTION_RESET: "the connection was reset partway through",
  TLS_ERROR: "the TLS connection could not be established",
  TOO_MANY_REDIRECTS: "it followed too many redirects",
  BLOCKED_REDIRECT_TARGET: "it was redirected somewhere we don't permit connecting to",
  HTTP_ERROR: "the request could not be completed",
};

interface IncompleteAssessmentBannerProps {
  incompleteModules: ModuleName[];
  modules: Modules;
}

function joinLabels(labels: string[]): string {
  if (labels.length <= 1) return labels.join("");
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/**
 * Contract §9 Step 4b (v3.0) / docs/Fix headers and incomplete.md §4.1
 * (v3.4): shown whenever `scan.is_complete === false`, regardless of
 * whether `overall_grade` itself is null — the one shared component for
 * this banner across the public result page (`ScanResultView`) and the
 * dashboard monitor page (`/dashboard/monitors/[id]`), so it can't render
 * on one and not the other the way the grade header itself once didn't
 * (see ScanGradeHeader's own docstring).
 *
 * Names which check(s) failed (§4.1 — `incomplete_modules` existed since
 * v3.0 precisely so this banner could stop saying only "1 of 7"). Appends
 * a short reason clause only when there's exactly one incomplete module and
 * it has one — a per-module reason for several at once belongs on each
 * module's own card (§4.3), not crammed into one sentence here.
 */
export function IncompleteAssessmentBanner({
  incompleteModules,
  modules,
}: IncompleteAssessmentBannerProps) {
  const labels = incompleteModules.map((name) => modules[name]?.label ?? name);
  const onlyName = incompleteModules.length === 1 ? incompleteModules[0] : undefined;
  const errorCode = onlyName !== undefined ? modules[onlyName]?.error?.code : undefined;
  const reason = errorCode ? REASON_PHRASE[errorCode] : undefined;

  return (
    <div
      role="alert"
      className="mb-6 rounded-card border border-alert/30 bg-alert/10 px-4 py-3 text-center text-sm text-ink"
    >
      <strong className="font-display">
        {incompleteModules.length} of 7 checks did not complete: {joinLabels(labels)}.
      </strong>{" "}
      This assessment is partial and should not be treated as a clean result
      {reason ? ` — ${reason}` : ""}.
    </div>
  );
}
