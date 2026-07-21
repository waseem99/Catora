import Link from "next/link";
import { BootstrapForm } from "@/components/bootstrap-form";

export default function SetupPage() {
  return (
    <main className="auth-shell">
      <section className="auth-panel setup-panel">
        <Link className="brand-link" href="/">Catora</Link>
        <p className="eyebrow">FIRST-RUN SETUP</p>
        <h1>Create the first protected workspace.</h1>
        <p className="lede">
          This endpoint works only before the first account exists. The first user becomes the
          organization owner and can invite the remaining team.
        </p>
        <BootstrapForm />
      </section>
    </main>
  );
}
