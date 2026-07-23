import "../onboarding.css";
import { CatalogOnboarding } from "@/components/catalog-onboarding";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function CatalogOnboardingPage({ params }: Props) {
  const { workspaceId } = await params;
  return <CatalogOnboarding workspaceId={workspaceId} />;
}
