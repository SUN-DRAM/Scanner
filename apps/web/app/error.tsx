"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";

interface ErrorPageProps {
  reset: () => void;
}

/** Next.js error boundary (contract §12 voice: state what happened and what
 * to do, never apologise) — without this, an unexpected failure anywhere in
 * the tree falls through to Next's generic, unstyled default error page. */
export default function ErrorPage({ reset }: ErrorPageProps) {
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-reading flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="font-display text-2xl leading-display text-ink">Something went wrong</h1>
      <p className="text-ink-muted">The page couldn&apos;t load. Try again, or start a new scan.</p>
      <div className="mt-2 flex items-center gap-4">
        <Button onClick={reset}>Try again</Button>
        <Link href="/" className="text-sm font-medium text-cobalt hover:underline">
          Start a new scan
        </Link>
      </div>
    </main>
  );
}
