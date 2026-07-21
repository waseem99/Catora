import { ProductBrowser } from "@/components/product-browser";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function ProductsPage({ params }: Props) {
  const { workspaceId } = await params;
  return (
    <main className="shell workspace-shell">
      <ProductBrowser workspaceId={workspaceId} />
    </main>
  );
}
