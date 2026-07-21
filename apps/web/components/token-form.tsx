"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/auth";

type Props = { mode: "invitation" | "reset"; token: string };

export function TokenForm({ mode, token }: Props) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setError(null);
    try {
      const path =
        mode === "invitation"
          ? "/api/v1/invitations/accept"
          : "/api/v1/auth/password/reset";
      const body =
        mode === "invitation"
          ? { token, display_name: data.get("display_name"), password: data.get("password") }
          : { token, password: data.get("password") };
      await apiRequest(path, { method: "POST", body: JSON.stringify(body) });
      router.replace(mode === "invitation" ? "/workspaces" : "/login");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The request could not be completed");
    }
  }

  return (
    <form className="auth-form" onSubmit={submit}>
      {mode === "invitation" ? (
        <label>
          Display name
          <input name="display_name" minLength={2} required />
        </label>
      ) : null}
      <label>
        New password
        <input name="password" type="password" minLength={12} required />
      </label>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <button className="primary-button" disabled={!token} type="submit">
        {mode === "invitation" ? "Accept invitation" : "Reset password"}
      </button>
    </form>
  );
}
