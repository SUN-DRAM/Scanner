import { redirect } from "next/navigation";

import { AdminLoginForm } from "@/components/admin/AdminLoginForm";
import { getAdminToken } from "@/lib/admin-session";
import { ApiRequestError, getAdminHealth } from "@/lib/api";

export default async function AdminLoginPage() {
  // Already holding a valid token → straight through to the console.
  const existing = await getAdminToken();
  if (existing) {
    let tokenIsValid = false;
    try {
      await getAdminHealth(existing);
      tokenIsValid = true;
    } catch (err) {
      // A 403 means a stale/revoked token — fall through to the form.
      // Anything else is a real failure worth surfacing.
      if (!(err instanceof ApiRequestError && err.status === 403)) {
        throw err;
      }
    }
    // redirect() throws NEXT_REDIRECT, so it must sit outside the try.
    if (tokenIsValid) {
      redirect("/admin/accounts");
    }
  }

  return (
    <main className="mx-auto flex max-w-reading flex-col px-4 py-24">
      <h1 className="mb-2 font-display text-2xl leading-display text-ink">Admin</h1>
      <p className="mb-8 text-sm leading-prose text-ink-muted">
        Internal console. Enter the operator token to continue.
      </p>
      <AdminLoginForm />
    </main>
  );
}
