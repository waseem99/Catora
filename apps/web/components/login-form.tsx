"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/auth";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setLoading(true);
    setError(null);
    try {
      await apiRequest("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: data.get("email"), password: data.get("password") }),
      });
      router.push("/workspaces");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign in");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={submit}>
      <label>
        Work email
        <input name="email" type="email" autoComplete="email" required />
      </label>
      <label>
        Password
        <input name="password" type="password" autoComplete="current-password" required />
      </label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="primary-button" disabled={loading} type="submit">
        {loading ? "Signing in…" : "Sign in"}
      </button>
      <a className="text-link" href="/forgot-password">Forgot password?</a>
    </form>
  );
}
