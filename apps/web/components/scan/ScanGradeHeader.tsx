import { GradeDial } from "@/components/scan/GradeDial";
import { cn, gradeTone, toneTextClass } from "@/lib/format";
import type { Grade } from "@/types/contract";

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
  headingLevel = 2,
  className,
}: ScanGradeHeaderProps) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  const tone = grade !== null ? gradeTone(grade) : null;

  return (
    <div className={cn("flex flex-col items-center gap-3 text-center", className)}>
      {grade !== null && score !== null && tone !== null ? (
        <>
          <GradeDial grade={grade} score={score} />
          <p
            className={cn(
              "font-mono text-xs font-medium uppercase tracking-wide",
              toneTextClass(tone),
            )}
          >
            Grade {grade} · {TONE_LABEL[tone]}
          </p>
        </>
      ) : null}
      {headline ? (
        <Heading className="max-w-reading font-display text-xl leading-display text-ink sm:text-2xl">
          {headline}
        </Heading>
      ) : null}
    </div>
  );
}
