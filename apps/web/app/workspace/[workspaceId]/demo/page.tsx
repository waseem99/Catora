import "./demo.css";
import { ClientDemo } from "@/components/client-demo";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function ClientDemoPage({ params }: Props) {
  const { workspaceId } = await params;
  return <ClientDemo workspaceId={workspaceId} />;
}
