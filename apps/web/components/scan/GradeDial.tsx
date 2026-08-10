import { gradeTone, toneTextClass } from "@/lib/format";
import type { Grade } from "@/types/contract";

const TONE_STROKE: Record<ReturnType<typeof gradeTone>, string> = {
  pass: "#0E9F6E",
  warn: "#E4A11B",
  alert: "#D7263D",
};

interface GradeDialProps {
  grade: Grade;
  score: number;
  size?: number;
}

const RADIUS = 54;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** The one fully-rounded element on the page, per contract §12. Colour is
 * never the sole carrier of meaning here: the letter grade and numeric
 * score are always printed alongside the ring. */
export function GradeDial({ grade, score, size = 152 }: GradeDialProps) {
  const tone = gradeTone(grade);
  const clamped = Math.max(0, Math.min(100, score));
  const offset = CIRCUMFERENCE * (1 - clamped / 100);

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Overall grade ${grade}, score ${score} out of 100`}
    >
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
        <circle cx="60" cy="60" r={RADIUS} fill="none" stroke="#E3E8ED" strokeWidth="10" />
        <circle
          cx="60"
          cy="60"
          r={RADIUS}
          fill="none"
          stroke={TONE_STROKE[tone]}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className={`font-display text-3xl leading-display ${toneTextClass(tone)}`}>
          {grade}
        </span>
        <span className="font-mono text-xs text-ink-muted">{clamped}/100</span>
      </div>
    </div>
  );
}
