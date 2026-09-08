import { cookies } from "next/headers";

import { ADMIN_COOKIE } from "@/lib/admin-session";
import { fetchAdminProspectCsv } from "@/lib/api";

/** Proxies the API's `text/csv` response, forwarding the operator's
 * `sd_admin` token — a page can't trigger a cross-origin authenticated
 * download, but a same-origin route handler can. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ batch_id: string }> },
): Promise<Response> {
  const { batch_id } = await params;
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) {
    return new Response("Not authorised.", { status: 401 });
  }

  const csv = await fetchAdminProspectCsv(batch_id, token);
  if (csv.status !== 200) {
    return new Response("Batch not found.", { status: csv.status === 403 ? 403 : 404 });
  }

  return new Response(csv.body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition":
        csv.contentDisposition ?? `attachment; filename="prospects-${batch_id}.csv"`,
      "Cache-Control": "no-store",
    },
  });
}
