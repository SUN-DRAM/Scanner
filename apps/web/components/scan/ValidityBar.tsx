import { formatDateDisplay } from "@/lib/format";

const THRESHOLD_ISO = "2027-03-15T00:00:00Z";
const THRESHOLD_LABEL = "15 Mar 2027";

interface ValidityBarProps {
  notBefore: string;
  notAfter: string;
  /** The instant to plot as "today" — passed in from the scan's own
   * `completed_at`/`created_at` rather than read from the client clock, so
   * server- and client-rendered output always agree (contract rule: the
   * frontend renders, it does not derive facts from a timestamp itself). */
  now: string;
  /** `readiness.data.survives_2027` — used only to caption the threshold
   * note when 15 March 2027 falls outside this certificate's own window. */
  survives2027: boolean | null;
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

/** The signature element (contract §12): not_before on the left, not_after
 * on the right, a marker for today, and — when it falls within this
 * certificate's own window — the 15 March 2027 threshold. */
export function ValidityBar({ notBefore, notAfter, now, survives2027 }: ValidityBarProps) {
  const start = new Date(notBefore).getTime();
  const end = new Date(notAfter).getTime();
  const today = new Date(now).getTime();
  const threshold = new Date(THRESHOLD_ISO).getTime();
  const span = end - start;

  const todayPercent = clampPercent(((today - start) / span) * 100);
  const thresholdWithinWindow = threshold >= start && threshold <= end;
  const thresholdPercent = thresholdWithinWindow
    ? clampPercent(((threshold - start) / span) * 100)
    : null;

  return (
    <div className="w-full">
      <div className="relative mb-3 h-2 rounded-full bg-line">
        <div
          className="absolute top-0 h-2 rounded-full bg-cobalt-soft"
          style={{ width: `${todayPercent}%` }}
        />
        <div
          className="absolute -top-1.5 h-5 w-0.5 bg-cobalt"
          style={{ left: `calc(${todayPercent}% - 1px)` }}
          title="Today"
        />
        {thresholdPercent !== null ? (
          <div
            className="absolute -top-1.5 h-5 w-0.5 bg-alert"
            style={{ left: `calc(${thresholdPercent}% - 1px)` }}
            title={`${THRESHOLD_LABEL} deadline`}
          />
        ) : null}
      </div>

      <div className="flex items-baseline justify-between font-mono text-xs text-ink-muted">
        <span>{formatDateDisplay(notBefore)}</span>
        <span>{formatDateDisplay(notAfter)}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-cobalt" /> Today
        </span>
        {thresholdPercent !== null ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-alert" /> {THRESHOLD_LABEL} deadline
          </span>
        ) : survives2027 !== null ? (
          <span>
            {survives2027
              ? `This certificate's window ends before the ${THRESHOLD_LABEL} deadline.`
              : `This certificate's window extends past the ${THRESHOLD_LABEL} deadline.`}
          </span>
        ) : null}
      </div>
    </div>
  );
}
