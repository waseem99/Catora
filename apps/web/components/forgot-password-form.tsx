"use client";
import { FormEvent, useState } from "react";
import { apiRequest } from "@/lib/auth";
export function ForgotPasswordForm() {
  const [sent, setSent] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await apiRequest("/api/v1/auth/password/forgot", { method: "POST", body: JSON.stringify({ email: data.get("email") }) });
    setSent(true);
  }
  if (sent) return <p>Check your email if an active account exists.</p>;
  return <form className="auth-form" onSubmit={submit}><label>Work email<input name="email" type="email" required /></label><button className="primary-button">Send reset link</button></form>;
}
