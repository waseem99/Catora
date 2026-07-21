import { TokenForm } from "@/components/token-form";

type Props = { searchParams: Promise<{ token?: string }> };

export default async function ResetPasswordPage({ searchParams }: Props) {
  const { token = "" } = await searchParams;
  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <h1>Choose a new password</h1>
        <TokenForm mode="reset" token={token} />
      </section>
    </main>
  );
}
