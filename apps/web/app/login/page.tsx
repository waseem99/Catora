import Link from "next/link";
import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <Link className="brand-link" href="/">Catora</Link>
        <p className="eyebrow">SECURE WORKSPACE</p>
        <h1>Sign in to your commerce intelligence workspace.</h1>
        <p className="lede">Sessions are server-side, revocable and scoped by organization membership.</p>
        <LoginForm />
        <p className="auth-footnote">First installation? <Link className="text-link" href="/setup">Create the owner workspace</Link></p>
      </section>
    </main>
  );
}
