import { ProductDetailPanel } from "@/components/product-detail-panel";

type Props = {
  params: Promise<{ workspaceId: string; productId: string }>;
};

export default async function ProductPage({ params }: Props) {
  const { workspaceId, productId } = await params;
  return (
    <main className="shell workspace-shell">
      <ProductDetailPanel productId={productId} workspaceId={workspaceId} />
    </main>
  );
}
