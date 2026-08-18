import { gradeTone } from "@/lib/format";
import { formatDateDisplay } from "@/lib/format";
import type { MonitorHistoryEntry } from "@/types/contract";

const TONE_STROKE: Record<ReturnType<typeof gradeTone>, string> = {
  pass: "#0E9F6E",
  warn: "#E4A11B",
  alert: "#D7263D",
};

interface GradeHistorySparklineProps {
  /** Newest first, as returned by `GET /monitors/{id}/history` (§7.9). */
  entries: MonitorHistoryEntry[];
  width?: number;
  height?: number;
}

/** A hand-rolled SVG dot-per-scan sparkline of `score` over time — no
 * charting dependency added for one small chart, same choice `GradeDial`
 * and `ValidityBar` already made for their own SVGs. */
export function GradeHistorySparkline({
  entries,
  width = 560,
  height = 72,
}: GradeHistorySparklineProps) {
  const scored = entries.filter((entry) => entry.score !== null).slice().reverse(); // oldest first, left to right

  if (scored.length === 0) {
    return <p className="text-sm text-ink-muted">No completed scans yet.</p>;
  }

  const padding = 8;
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const stepX = scored.length > 1 ? plotWidth / (scored.length - 1) : 0;

  function pointFor(index: number, score: number): { x: number; y: number } {
    const x = padding + index * stepX;
    const y = padding + plotHeight * (1 - Math.max(0, Math.min(100, score)) / 100);
    return { x, y };
  }

  const linePath = scored
    .map((entry, index) => {
      const { x, y } = pointFor(index, entry.score as number);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // Non-null: the `scored.length === 0` check above guarantees at least one entry.
  const first = scored[0]!;
  const last = scored[scored.length - 1]!;

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Grade history">
        <path d={linePath} fill="none" stroke="#E3E8ED" strokeWidth="2" />
        {scored.map((entry, index) => {
          const { x, y } = pointFor(index, entry.score as number);
          const tone = entry.grade !== null ? gradeTone(entry.grade) : "warn";
          return <circle key={entry.scan_id} cx={x} cy={y} r="3.5" fill={TONE_STROKE[tone]} />;
        })}
      </svg>
      <div className="mt-1 flex justify-between font-mono text-xs text-ink-muted">
        <span>{formatDateDisplay(first.scanned_at)}</span>
        <span>{formatDateDisplay(last.scanned_at)}</span>
      </div>
    </div>
  );
}
