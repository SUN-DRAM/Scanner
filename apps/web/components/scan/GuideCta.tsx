import { ScanForm } from "@/components/scan/ScanForm";

interface GuideCtaProps {
  heading?: string;
}

export function GuideCta({ heading = "Check where you actually stand" }: GuideCtaProps) {
  return (
    <div className="mt-12 flex flex-col items-center gap-4 rounded-card border border-line bg-surface px-6 py-10 text-center">
      <h2 className="font-display text-xl leading-display text-ink">{heading}</h2>
      <p className="max-w-reading text-sm text-ink-muted">
        Enter a hostname and get a graded TLS and DNS report in under 20 seconds. Free, no signup,
        share the link with anyone.
      </p>
      <ScanForm />
    </div>
  );
}
