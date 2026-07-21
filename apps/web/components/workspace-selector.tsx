"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest, type AuthUser } from "@/lib/auth";

export function WorkspaceSelector() {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<AuthUser>("/api/v1/auth/me")
      .then(setUser)
      .catch(() => router.replace("/login"));
  }, [router]);

  async function logout() {
    try {
      await apiRequest<void>("/api/v1/auth/logout", { method: "POST" });
      router.replace("/login");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign out");
    }
  }

  if (!user) return <p className="loading-state">Loading your workspaces…</p>;

  return (
    <section className="workspace-panel">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">WELCOME BACK</p>
          <h1>{user.display_name}</h1>
          <p>{user.email}</p>
        </div>
        <button className="secondary-button" onClick={logout} type="button">Sign out</button>
      </header>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <div className="workspace-grid">
        {user.memberships.map((membership) => (
          <Link className="workspace-card" href={`/workspace/${membership.workspace_id}`} key={membership.workspace_id}>
            <span>{membership.organization_name}</span>
            <strong>{membership.workspace_name}</strong>
            <small>{membership.role}</small>
          </Link>
        ))}
      </div>
      {user.memberships.length === 0 ? <p>No active workspace memberships.</p> : null}
    </section>
  );
}
