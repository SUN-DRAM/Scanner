import { GradeDial } from "@/components/scan/GradeDial";
import { cn, gradeTone, toneTextClass } from "@/lib/format";
import type { Grade } from "@/types/contract";

/**
 * Contract §9 Step 4b (v3.0): when `certificate` didn't complete, the scan
 * has no grade at all — this renders in the exact spot `GradeDial` would,
 * same footprint, so "Incomplete" never reads as a layout glitch. Never a
 * letter, never blank space where a letter would have been.
 */
function IncompleteGradeDial({ size = 152 }: { size?: number }) {
  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label="No grade — this assessment is incomplete"
    >
      <svg viewBox="0 0 120 120" className="h-full w-full">
        <circle
          cx="60"
          cy="60"
          r="54"
          fill="none"
          stroke="#E3E8ED"
          strokeWidth="10"
          strokeDasharray="4 6"
        />
      </svg>
      <div className="absolute flex flex-col items-center px-4 text-center">
        <span className="font-display text-lg leading-display text-ink-muted">Incomplete</span>
      </div>
    </div>
  );
}

/** Contract §12: colour never carries meaning alone — every grade colour is
 * paired with the letter grade and a plain-language label. */
const TONE_LABEL: Record<ReturnType<typeof gradeTone>, string> = {
  pass: "Pass",
  warn: "Needs attention",
  alert: "Action needed",
};

interface ScanGradeHeaderProps {
  grade: Grade | null;
  score: number | null;
  headline: string | null;
  /** Contract §9 Step 4 (v3.1): why the letter reads worse than its own
   * score bands to — e.g. "capped by 2 high-severity findings" — or `null`
   * when there's nothing to reconcile. Backend-computed (CLAUDE.md rule 3);
   * this component only ever displays it, never re-derives it from
   * `grade`/`score` itself. */
  gradeCapReason?: string | null;
  /** docs/Fix headers and incomplete.md §4.2: `scan.is_complete` — `false`
   * means at least one module didn't run, so `score` is biased upward by an
   * unknown amount (its weight redistributed to the modules that did
   * complete). Renders the score as a ceiling in that case. `undefined`/
   * `null` (queued/running/failed, or a surface that never passes it) reads
   * as complete — never show the caveat without a positive reason to. */
  isComplete?: boolean | null;
  /** Heading tag for the headline sentence — `1` on the standalone public
   * share page, `2` inside the dashboard's "Latest result" section. The
   * grade dial, score and tone label render identically either way. */
  headingLevel?: 1 | 2;
  /** Extra classes for the wrapper, so each page keeps its own alignment
   * (centred hero vs. left-aligned dashboard block). */
  className?: string;
}

/**
 * The overall grade dial, numeric score, tone label, and headline for a
 * completed scan. The single source of this markup for both the public
 * share page (`ScanResultView`) and the dashboard monitor page
 * (`/dashboard/monitors/[id]`) — extracted here so the grade can never
 * again render on one and not the other (CLAUDE.md rule 4: the components a
 * result page is built from change once and are used in both places).
 */
export function ScanGradeHeader({
  grade,
  score,
  headline,
  gradeCapReason,
  isComplete,
  headingLevel = 2,
  className,
}: ScanGradeHeaderProps) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  const tone = grade !== null ? gradeTone(grade) : null;

  return (
    <div className={cn("flex flex-col items-center gap-3 text-center", className)}>
      {grade !== null && score !== null && tone !== null ? (
        <>
          <GradeDial grade={grade} score={score} scoreIsCeiling={isComplete === false} />
          <p
            className={cn(
              "font-mono text-xs font-medium uppercase tracking-wide",
              toneTextClass(tone),
            )}
          >
            Grade {grade} · {TONE_LABEL[tone]}
          </p>
          {gradeCapReason ? (
            <p className="text-xs text-ink-muted">
              {grade} — {gradeCapReason}
            </p>
          ) : null}
        </>
      ) : (
        <IncompleteGradeDial />
      )}
      {headline ? (
        <Heading className="max-w-reading font-display text-xl leading-display text-ink sm:text-2xl">
          {headline}
        </Heading>
      ) : null}
    </div>
  );
}
