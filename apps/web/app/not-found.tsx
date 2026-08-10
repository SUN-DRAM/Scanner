import Link from "next/link";

export default function NotFoundPage() {
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-reading flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="font-display text-2xl leading-display text-ink">Page not found</h1>
      <p className="text-ink-muted">Check the link, or start a new scan.</p>
      <Link href="/" className="font-medium text-cobalt hover:underline">
        Start a new scan
      </Link>
    </main>
  );
}
