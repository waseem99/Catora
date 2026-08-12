import { z } from "zod";
import { apiRequest } from "./auth";
import { backendApiPath } from "./backend-path";

const uuid = z.string().uuid();

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

export const ServiceVisibilityReportPageSchema = z.object({
  url: z.string(),
  title: z.string(),
  meta_description: z.string(),
  visible_text: z.string(),
  headings: z.array(z.object({ level: z.string(), text: z.string() })),
  wordpress: z.object({
    post_id: z.number().int().positive().optional(),
    revision: z.string().min(1).optional(),
    builder: z.string().optional(),
  }).passthrough(),
});

export const ServiceVisibilityFindingSchema = z.object({
  fingerprint: z.string(),
  code: z.string(),
  family: z.enum(["technical_seo", "aeo", "ai_discovery", "architecture"]),
  severity: z.enum(["critical", "high", "medium", "low", "informational"]),
  lifecycle: z.enum(["new", "persisting"]),
  title: z.string(),
  detail: z.string(),
  recommendation: z.string(),
  page_url: z.string().nullable(),
  evidence: z.array(z.object({ url: z.string(), excerpt: z.string() })),
});

export const ServiceVisibilityReportSchema = z.object({
  source_id: uuid,
  site: z.object({
    company_name: z.string(),
    pages: z.array(ServiceVisibilityReportPageSchema),
  }),
  findings: z.array(ServiceVisibilityFindingSchema),
});

export const ServiceVisibilityDraftSchema = z.object({
  id: uuid,
  source_id: uuid,
  report_id: uuid,
  status: z.string(),
  page_url: z.string(),
  wordpress_post_id: z.number().int().positive(),
  base_revision: z.string(),
  proposal: z.record(z.string(), z.unknown()),
  approved_at: z.string().nullable(),
  remote_draft_id: z.number().int().positive().nullable(),
  error: z.string().nullable(),
});

export type ServiceVisibilitySource = z.infer<typeof ServiceVisibilitySourceSchema>;
export type ServiceVisibilityProvision = z.infer<typeof ServiceVisibilityProvisionSchema>;
export type ServiceVisibilityRun = z.infer<typeof ServiceVisibilityRunSchema>;
export type ServiceVisibilityReport = z.infer<typeof ServiceVisibilityReportSchema>;
export type ServiceVisibilityFinding = z.infer<typeof ServiceVisibilityFindingSchema>;
export type ServiceVisibilityReportPage = z.infer<typeof ServiceVisibilityReportPageSchema>;
export type ServiceVisibilityDraft = z.infer<typeof ServiceVisibilityDraftSchema>;

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

export async function getServiceVisibilityReport(
  workspaceId: string,
  reportId: string,
): Promise<ServiceVisibilityReport> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/runs/${reportId}/artifacts/service_visibility_json`,
  );
  return ServiceVisibilityReportSchema.parse(value);
}

export async function createServiceVisibilityDraft(
  workspaceId: string,
  reportId: string,
  input: {
    page_url: string;
    wordpress_post_id: number;
    base_revision: string;
    title?: string;
    content?: string;
    meta_title?: string;
    meta_description?: string;
  },
): Promise<ServiceVisibilityDraft> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/runs/${reportId}/drafts`,
    { method: "POST", body: JSON.stringify(input) },
  );
  return ServiceVisibilityDraftSchema.parse(value);
}

export async function approveServiceVisibilityDraft(
  workspaceId: string,
  sourceId: string,
  draftId: string,
): Promise<ServiceVisibilityDraft> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/service-visibility/sources/${sourceId}/drafts/${draftId}/approve`,
    { method: "POST" },
  );
  return ServiceVisibilityDraftSchema.parse(value);
}

export function serviceVisibilityArtifactUrl(
  workspaceId: string,
  reportId: string,
  artifactType: string,
): string {
  return backendApiPath(
    `/api/v1/workspaces/${workspaceId}/service-visibility/runs/${reportId}/artifacts/${artifactType}`,
  );
}
