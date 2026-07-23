import "../../diagnostic.css";
import { ProspectDiagnostic } from "@/components/prospect-diagnostic";

type Props = {
  params: Promise<{ workspaceId: string; assessmentId: string }>;
};

export default async function ProspectDiagnosticPage({ params }: Props) {
  const { workspaceId, assessmentId } = await params;
  return <ProspectDiagnostic workspaceId={workspaceId} assessmentId={assessmentId} />;
}
