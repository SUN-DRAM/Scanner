interface IncompleteAssessmentBannerProps {
  incompleteModuleCount: number;
}

/**
 * Contract §9 Step 4b (v3.0): shown whenever `scan.is_complete === false`,
 * regardless of whether `overall_grade` itself is null — the one shared
 * component for this banner across the public result page
 * (`ScanResultView`) and the dashboard monitor page
 * (`/dashboard/monitors/[id]`), so it can't render on one and not the other
 * the way the grade header itself once didn't (see ScanGradeHeader's own
 * docstring).
 */
export function IncompleteAssessmentBanner({
  incompleteModuleCount,
}: IncompleteAssessmentBannerProps) {
  return (
    <div
      role="alert"
      className="mb-6 rounded-card border border-alert/30 bg-alert/10 px-4 py-3 text-center text-sm text-ink"
    >
      <strong className="font-display">
        {incompleteModuleCount} of 7 checks did not complete.
      </strong>{" "}
      This assessment is partial and should not be treated as a clean result.
    </div>
  );
}
