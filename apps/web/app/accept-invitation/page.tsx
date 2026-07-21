import { TokenForm } from "@/components/token-form";

type Props = { searchParams: Promise<{ token?: string }> };

export default async function AcceptInvitationPage({ searchParams }: Props) {
  const { token = "" } = await searchParams;
  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <h1>Join Catora</h1>
        <TokenForm mode="invitation" token={token} />
      </section>
    </main>
  );
}
