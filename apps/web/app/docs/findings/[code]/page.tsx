import fs from "node:fs/promises";
import path from "node:path";

import type { Metadata } from "next";
import Link from "next/link";
import { marked } from "marked";

import { Badge } from "@/components/ui/badge";
import { severityLabel, severityTone } from "@/lib/format";
import { codeToSlug, FINDINGS_CATALOGUE, slugToCode } from "@/lib/findings-catalogue";

interface DocsFindingPageProps {
  params: Promise<{ code: string }>;
}

export function generateStaticParams(): { code: string }[] {
  return FINDINGS_CATALOGUE.map((entry) => ({ code: codeToSlug(entry.code) }));
}

async function loadFindingDoc(code: string): Promise<string | null> {
  // docs/findings/*.md is authored at the repo root (contract §3.2, written
  // in Step 8) and bind-mounted into the web container at ./docs — see
  // docker-compose.yml's `web` service.
  const filePath = path.join(process.cwd(), "docs", "findings", `${codeToSlug(code)}.md`);
  try {
    return await fs.readFile(filePath, "utf-8");
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: DocsFindingPageProps): Promise<Metadata> {
  const { code: slug } = await params;
  const code = slugToCode(slug);
  if (!code) return { title: "Finding not found" };

  const title = code.replaceAll("_", " ").toLowerCase();
  return {
    title: `${title} — findings reference`,
    alternates: { canonical: `/docs/findings/${slug}` },
  };
}

export default async function DocsFindingPage({ params }: DocsFindingPageProps) {
  const { code: slug } = await params;
  const code = slugToCode(slug);

  if (!code) {
    return (
      <main className="mx-auto flex max-w-reading flex-col items-center gap-4 px-4 py-24 text-center">
        <h1 className="font-display text-2xl leading-display text-ink">
          This finding code doesn&apos;t exist
        </h1>
        <Link href="/" className="font-medium text-cobalt hover:underline">
          Back to the scanner
        </Link>
      </main>
    );
  }

  const entry = FINDINGS_CATALOGUE.find((item) => item.code === code);
  const markdown = await loadFindingDoc(code);
  const tone = entry ? severityTone(entry.severity) : "neutral";

  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <p className="font-mono text-xs text-ink-muted">{code}</p>
      <div className="mt-3 flex items-center gap-3">
        {entry ? <Badge variant={tone}>{severityLabel(entry.severity)}</Badge> : null}
        {entry ? <span className="text-sm text-ink-muted">{entry.module}</span> : null}
      </div>

      {markdown ? (
        <article
          className="prose-content mt-6 leading-prose text-ink"
          // First-party content authored in this repo's docs/findings/*.md — not user input.
          dangerouslySetInnerHTML={{ __html: await marked.parse(markdown) }}
        />
      ) : (
        <p className="mt-6 text-ink-muted">
          The written explanation for this finding is being prepared. Check back shortly.
        </p>
      )}

      <Link href="/" className="mt-10 inline-block font-medium text-cobalt hover:underline">
        Back to the scanner
      </Link>
    </main>
  );
}
