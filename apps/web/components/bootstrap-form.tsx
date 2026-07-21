"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/auth";

export function BootstrapForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setLoading(true);
    setError(null);
    try {
      await apiRequest("/api/v1/auth/bootstrap", {
        method: "POST",
        body: JSON.stringify({
          organization_name: data.get("organization_name"),
          organization_slug: data.get("organization_slug"),
          workspace_name: data.get("workspace_name"),
          workspace_slug: data.get("workspace_slug"),
          display_name: data.get("display_name"),
          email: data.get("email"),
          password: data.get("password"),
        }),
      });
      router.push("/workspaces");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to initialize Catora");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="auth-form two-column-form" onSubmit={submit}>
      <label>
        Organization name
        <input name="organization_name" required minLength={2} />
      </label>
      <label>
        Organization slug
        <input name="organization_slug" required pattern="[a-z0-9][a-z0-9-]{1,98}[a-z0-9]" />
      </label>
      <label>
        Workspace name
        <input name="workspace_name" required minLength={2} />
      </label>
      <label>
        Workspace slug
        <input name="workspace_slug" required pattern="[a-z0-9][a-z0-9-]{1,98}[a-z0-9]" />
      </label>
      <label>
        Owner name
        <input name="display_name" required minLength={2} autoComplete="name" />
      </label>
      <label>
        Owner email
        <input name="email" type="email" required autoComplete="email" />
      </label>
      <label className="full-row">
        Password
        <input name="password" type="password" required minLength={12} autoComplete="new-password" />
      </label>
      {error ? <p className="form-error full-row" role="alert">{error}</p> : null}
      <button className="primary-button full-row" disabled={loading} type="submit">
        {loading ? "Creating workspace…" : "Create first workspace"}
      </button>
    </form>
  );
}
