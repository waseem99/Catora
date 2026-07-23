import "../../onboarding.css";
import { ProcessingJourney } from "@/components/processing-journey";

type Props = { params: Promise<{ workspaceId: string; jobId: string }> };

export default async function CatalogProcessingPage({ params }: Props) {
  const { workspaceId, jobId } = await params;
  return <ProcessingJourney workspaceId={workspaceId} jobId={jobId} />;
}
