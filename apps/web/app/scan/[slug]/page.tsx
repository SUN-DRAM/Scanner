import type { Metadata } from "next";
import Link from "next/link";

import { ScanResultView } from "@/components/scan/ScanResultView";
import { ApiRequestError, getScanBySlug } from "@/lib/api";
import type { Scan } from "@/types/contract";

interface ScanResultPageProps {
  params: Promise<{ slug: string }>;
}

async function loadScan(slug: string): Promise<Scan | null> {
  try {
    return await getScanBySlug(slug);
  } catch (err) {
    if (err instanceof ApiRequestError && err.code === "SCAN_NOT_FOUND") {
      return null;
    }
    throw err;
  }
}

export async function generateMetadata({ params }: ScanResultPageProps): Promise<Metadata> {
  const { slug } = await params;
  const scan = await loadScan(slug);

  if (!scan) {
    return { title: "Scan not found" };
  }

  const title =
    scan.overall_grade !== null
      ? `${scan.hostname} — Grade ${scan.overall_grade}`
      : `${scan.hostname} — scanning`;
  const description = scan.headline ?? `TLS and DNS scan results for ${scan.hostname}.`;

  return {
    title,
    description,
    alternates: { canonical: `/scan/${slug}` },
    openGraph: { title, description },
    twitter: { card: "summary", title, description },
  };
}

export default async function ScanResultPage({ params }: ScanResultPageProps) {
  const { slug } = await params;
  const scan = await loadScan(slug);

  if (!scan) {
    return (
      <main className="mx-auto flex max-w-reading flex-col items-center gap-4 px-4 py-24 text-center">
        <h1 className="font-display text-2xl leading-display text-ink">
          This scan link doesn&apos;t exist
        </h1>
        <p className="text-ink-muted">Check the link, or start a new scan.</p>
        <Link href="/" className="font-medium text-cobalt hover:underline">
          Start a new scan
        </Link>
      </main>
    );
  }

  return <ScanResultView initialScan={scan} />;
}
