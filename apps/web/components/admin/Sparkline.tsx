import { formatIsoDateDisplay } from "@/lib/format";
import type { AdminFunnelPoint } from "@/types/contract";

/** A hand-rolled inline-SVG area sparkline — no charting dependency, same
 * choice `GradeDial` / `ValidityBar` / `GradeHistorySparkline` already made.
 * Monochrome (contract §12 ink), because this is an operator instrument. */
export function Sparkline({ points, height = 52 }: { points: AdminFunnelPoint[]; height?: number }) {
  if (points.length === 0) {
    return <p className="text-sm text-ink-muted">No data.</p>;
  }

  const width = 480;
  const pad = 4;
  const max = Math.max(1, ...points.map((point) => point.value));
  const total = points.reduce((sum, point) => sum + point.value, 0);
  const plotHeight = height - pad * 2;
  const stepX = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;

  const coords = points.map((point, index) => ({
    x: pad + index * stepX,
    y: pad + plotHeight * (1 - point.value / max),
  }));
  const line = coords
    .map((coord, index) => `${index === 0 ? "M" : "L"}${coord.x.toFixed(1)},${coord.y.toFixed(1)}`)
    .join(" ");
  const baseline = height - pad;
  const first = coords[0]!;
  const last = coords[coords.length - 1]!;
  const area = `${line} L${last.x.toFixed(1)},${baseline} L${first.x.toFixed(1)},${baseline} Z`;

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label="30-day trend"
        preserveAspectRatio="none"
      >
        <path d={area} fill="#0B1B2B" fillOpacity="0.06" />
        <path d={line} fill="none" stroke="#0B1B2B" strokeWidth="1.5" />
      </svg>
      <div className="mt-1 flex justify-between font-mono text-xs text-ink-muted">
        <span>{formatIsoDateDisplay(points[0]!.date)}</span>
        <span>
          {total} total · peak {max}
        </span>
        <span>{formatIsoDateDisplay(points[points.length - 1]!.date)}</span>
      </div>
    </div>
  );
}
