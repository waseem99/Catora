import "./demo.css";
import { ClientDemo } from "@/components/client-demo";
import { PresenterReadiness } from "@/components/presenter-readiness";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function ClientDemoPage({ params }: Props) {
  const { workspaceId } = await params;
  return (
    <>
      <PresenterReadiness workspaceId={workspaceId} />
      <ClientDemo workspaceId={workspaceId} />
    </>
  );
}
