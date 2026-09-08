import { AdminShell } from "@/components/admin/AdminShell";
import { requireAdminToken } from "@/lib/admin-session";

// Every `/admin/*` console page (not `/admin/login`) is gated here once.
export default async function AdminDashLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireAdminToken();
  return <AdminShell>{children}</AdminShell>;
}
