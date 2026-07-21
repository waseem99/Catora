import Link from "next/link";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function WorkspacePage({ params }: Props) {
  const { workspaceId } = await params;
  return (
    <main className="shell workspace-shell">
      <p className="eyebrow">WORKSPACE READY</p>
      <h1>Catalog intelligence</h1>
      <p className="lede">
        Review canonical products, normalization warnings, identity candidates and source evidence
        for this workspace.
      </p>
      <div className="actions">
        <Link className="primary" href={`/workspace/${workspaceId}/products`}>
          Browse products
        </Link>
        <Link className="secondary" href={`/workspace/${workspaceId}/identity-review`}>
          Review identities
        </Link>
        <Link className="secondary" href={`/workspace/${workspaceId}/members`}>
          Manage access
        </Link>
        <Link className="secondary" href="/workspaces">
          Back to workspaces
        </Link>
      </div>
    </main>
  );
}
