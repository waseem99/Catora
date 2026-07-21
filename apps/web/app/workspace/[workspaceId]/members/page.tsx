"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { MemberAdmin } from "@/components/member-admin";
import { apiRequest, type AuthUser, type RoleName } from "@/lib/auth";

export default function MembersPage() {
  const params = useParams<{ workspaceId: string }>();
  const router = useRouter();
  const [role, setRole] = useState<RoleName | null>(null);

  useEffect(() => {
    apiRequest<AuthUser>("/api/v1/auth/me")
      .then((user) => {
        const membership = user.memberships.find((item) => item.workspace_id === params.workspaceId);
        if (!membership) {
          router.replace("/workspaces");
          return;
        }
        setRole(membership.role);
      })
      .catch(() => router.replace("/login"));
  }, [params.workspaceId, router]);

  if (!role) return <main className="shell workspace-shell"><p>Loading access controls…</p></main>;

  return (
    <main className="shell workspace-shell">
      <Link className="text-link" href={`/workspace/${params.workspaceId}`}>Back to workspace</Link>
      <MemberAdmin workspaceId={params.workspaceId} currentRole={role} />
    </main>
  );
}
