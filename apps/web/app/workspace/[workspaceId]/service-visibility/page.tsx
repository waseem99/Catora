import "./service-visibility.css";
import { ServiceVisibilityConsole } from "@/components/service-visibility-console";

type Props = { params: Promise<{ workspaceId: string }> };

export default async function ServiceVisibilityPage({ params }: Props) {
  const { workspaceId } = await params;
  return <ServiceVisibilityConsole workspaceId={workspaceId} />;
}
