import { IdentityReviewQueue } from "@/components/identity-review-queue";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function IdentityReviewPage({ params }: Props) {
  const { workspaceId } = await params;
  return (
    <main className="shell workspace-shell">
      <IdentityReviewQueue workspaceId={workspaceId} />
    </main>
  );
}
