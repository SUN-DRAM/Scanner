import { Button } from "@/components/ui/button";
import { scanReportPdfUrl } from "@/lib/api";

interface DownloadReportButtonProps {
  scanId: string;
}

/**
 * Contract §7.14 (v2.9): `.../report.pdf` returns `409 REPORT_NOT_AVAILABLE`
 * for anything other than a completed scan, so the caller (ScanResultView)
 * only renders this once `scan.status === "completed"` — this component
 * itself takes no status prop and does no check, so there is exactly one
 * place that gate lives, not two that could drift apart.
 */
export function DownloadReportButton({ scanId }: DownloadReportButtonProps) {
  return (
    <Button asChild variant="secondary" size="sm">
      <a href={scanReportPdfUrl(scanId)}>Download PDF report</a>
    </Button>
  );
}
