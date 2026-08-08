import { z } from "zod";
import { apiRequest } from "./auth";

const uuid = z.string().uuid();
const apiUrl = process.env.NEXT_PUBLIC_CATORA_API_URL ?? "http://localhost:8000";

export const ServiceVisibilitySourceSchema = z.object({
  id: uuid,
  workspace_id: uuid,
  name: z.string(),
  site_url: z.string(),
  connection_mode: z.enum(["zero_install", "wordpress_bridge"]),
  status: z.string(),
  monitoring_enabled: z.boolean(),
  token_fingerprint: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const ServiceVisibilityProvisionSchema = ServiceVisibilitySourceSchema.extend({
  endpoint: z.string(),
  token: z.string().nullable(),
});

export const ServiceVisibilityRunSchema = z.object({
  id: uuid,
  workspace_id: uuid,
  source_id: uuid,
  ingestion_job_id: uuid,
  status: z.string(),
  scorecard: z.record(z.string(), z.number().int()),
  page_count: z.number().int().nonnegative(),
  finding_count: z.number().int().nonnegative(),
  question_count: z.number().int().nonnegative(),
  continuity: z.record(z.string(), z.unknown()),
  artifacts: z.array(z.string()),
  error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type ServiceVisibilitySource = z.infer<typeof ServiceVisibilitySourceSchema>;
export type ServiceVisibilityProvision = z.infer<typeof ServiceVisibilityProvisionSchema>;
export type ServiceVisibilityRun = z.infer<typeof ServiceVisibilityRunSchema>;

export async function createServiceVisibilitySource(
  workspaceId: string,
  input: {
    name: string;
    site_url: string;
    connection_mode: "zero_install" | "wordpress_bridge";
    authorized_domain_confirmed: true;
    monitoring_enabled: boolean;
  },
): Promise<ServiceVisibilityProvision> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/sources`,
    { method: "POST", body: JSON.stringify(input) },
  );
  return ServiceVisibilityProvisionSchema.parse(value);
}

export async function listServiceVisibilitySources(
  workspaceId: string,
): Promise<ServiceVisibilitySource[]> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/sources`,
  );
  return z.array(ServiceVisibilitySourceSchema).parse(value);
}

export async function rotateServiceVisibilitySource(
  workspaceId: string,
  sourceId: string,
): Promise<ServiceVisibilityProvision> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/sources/${sourceId}/rotate`,
    { method: "POST" },
  );
  return ServiceVisibilityProvisionSchema.parse(value);
}

export async function runServiceVisibility(
  workspaceId: string,
  sourceId: string,
): Promise<ServiceVisibilityRun> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/sources/${sourceId}/runs`,
    { method: "POST" },
  );
  return ServiceVisibilityRunSchema.parse(value);
}

export async function listServiceVisibilityRuns(
  workspaceId: string,
): Promise<ServiceVisibilityRun[]> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/runs`,
  );
  return z.array(ServiceVisibilityRunSchema).parse(value);
}

export function serviceVisibilityArtifactUrl(
  workspaceId: string,
  reportId: string,
  artifactType: string,
): string {
  return `${apiUrl}/api/v1/workspaces/${workspaceId}/service-visibility/runs/${reportId}/artifacts/${artifactType}`;
}
