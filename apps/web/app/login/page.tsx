import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/auth/LoginForm";
import { ApiRequestError, getMe } from "@/lib/api";
import { getForwardedCookie } from "@/lib/session";

export const metadata: Metadata = {
  title: "Sign in",
  alternates: { canonical: "/login" },
};

export default async function LoginPage() {
  const cookie = await getForwardedCookie();
  try {
    await getMe(cookie);
    redirect("/app");
  } catch (err) {
    if (!(err instanceof ApiRequestError && err.code === "UNAUTHENTICATED")) {
      throw err;
    }
  }

  return (
    <main className="mx-auto flex max-w-reading flex-col items-center px-4 py-24">
      <h1 className="mb-8 text-center font-display text-2xl leading-display text-ink">
        Sign in to SUN-DRAM Scanner
      </h1>
      <LoginForm />
    </main>
  );
}
