"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { logout } from "@/lib/api";
import { cn } from "@/lib/format";

interface SignOutButtonProps {
  className?: string;
}

/** Calls the real `POST /api/v1/auth/logout` (contract §7.6/§7.7), which
 * revokes the session server-side and clears the `sd_session` cookie —
 * there is no client-side token to clear, the cookie is `httpOnly` by
 * design. `router.refresh()` re-runs every server component on the next
 * render so a stale "logged in" server-rendered header never lingers. */
export function SignOutButton({ className }: SignOutButtonProps) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <button
      type="button"
      onClick={handleSignOut}
      disabled={signingOut}
      className={cn(
        "font-medium text-ink-muted transition-colors hover:text-ink hover:underline disabled:opacity-50",
        className,
      )}
    >
      {signingOut ? "Signing out…" : "Sign out"}
    </button>
  );
}
