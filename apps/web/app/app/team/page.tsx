import type { Metadata } from "next";

import { TeamManager } from "@/components/app/TeamManager";
import { getMe, listMembers } from "@/lib/api";
import { getForwardedCookie } from "@/lib/session";

export const metadata: Metadata = { title: "Team" };

export default async function TeamPage() {
  const cookie = await getForwardedCookie();
  const [members, me] = await Promise.all([
    listMembers({ per_page: 100 }, cookie),
    getMe(cookie),
  ]);

  return (
    <div>
      <h1 className="mb-6 font-display text-xl leading-display text-ink">Team</h1>
      <TeamManager initialMembers={members.items} currentUserId={me.user_id} />
    </div>
  );
}
