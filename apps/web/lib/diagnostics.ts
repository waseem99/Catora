import { z } from "zod";
import { apiRequest, csrfToken } from "./auth";

const apiUrl = process.env.NEXT_PUBLIC_CATORA_API_URL ?? "http://localhost:8000";
const uuid = z.string().uuid();

export const DiagnosticStatusSchema = z.enum([
  "awaiting_upload",
  "queued",
  "ingesting",
  "normalizing",
  "categorizing",
  "auditing",
  "matching",
  "preparing_reports",
  "completed",
  "failed",
  "deleting",
]);

export const DiagnosticCountsSchema = z.object({
  processed_rows: z.number().int().nonnegative(),
  accepted_rows: z.number().int().nonnegative(),
  rejected_rows: z.number().int().nonnegative(),
  warning_count: z.number().int().nonnegative(),
  product_count: z.number().int().nonnegative(),
  variant_count: z.number().int().nonnegative(),
  assigned_category_count: z.number().int().nonnegative(),
  ambiguous_category_count: z.number().int().nonnegative(),
  unclassified_category_count: z.number().int().nonnegative(),
  finding_count: z.number().int().nonnegative(),
  intent_run_count: z.number().int().nonnegative(),
  intent_match_count: z.number().int().nonnegative(),
});

export const DiagnosticSchema = z.object({
  id: uuid,
  workspace_id: uuid,
  organization_id: uuid,
  company_name: z.string(),
  status: DiagnosticStatusSchema,
  current_stage: z.string(),
  detail: z.string(),
  market_code: z.string(),
  locale: z.string(),
  currency: z.string(),
  retention_expires_at: z.string(),
  counts: DiagnosticCountsSchema,
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
  failure_code: z.string().nullable(),
  failure_detail: z.string().nullable(),
  ingestion_job_id: uuid.nullable(),
  audit_run_id: uuid.nullable(),
  intent_run_ids: z.array(uuid),
  result_path: z.string(),
  report_path: z.string(),
  backlog_path: z.string(),
  rejection_path: z.string(),
});

export const DiagnosticRejectionSchema = z.object({
  row_number: z.number().int().positive(),
  reason: z.string(),
  product_handle: z.string().nullable(),
  variant_sku: z.string().nullable(),
});

export const DiagnosticRejectionListSchema = z.object({
  items: z.array(DiagnosticRejectionSchema),
  total_rejected: z.number().int().nonnegative(),
  sample_limit: z.number().int().positive(),
});

export type Diagnostic = z.infer<typeof DiagnosticSchema>;
export type DiagnosticStatus = z.infer<typeof DiagnosticStatusSchema>;
export type DiagnosticRejectionList = z.infer<typeof DiagnosticRejectionListSchema>;

export type CreateDiagnosticInput = {
  company_name: string;
  market_code: string;
  locale: string;
  currency: string;
  retention_days: number;
  authorization_confirmed: boolean;
  storefront_domain?: string;
};

export async function createDiagnostic(
  operatorWorkspaceId: string,
  input: CreateDiagnosticInput,
): Promise<Diagnostic> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${operatorWorkspaceId}/prospect-diagnostics`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
  return DiagnosticSchema.parse(payload);
}

export async function uploadDiagnosticCsv(
  assessmentId: string,
  file: File,
): Promise<Diagnostic> {
  const headers = new Headers({
    Accept: "application/json",
    "Content-Type": "text/csv",
  });
  const csrf = csrfToken();
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(
    `${apiUrl}/api/v1/prospect-diagnostics/${assessmentId}/catalog.csv`,
    {
      method: "PUT",
      headers,
      body: file,
      credentials: "include",
    },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Upload failed with status ${response.status}`);
  }
  return DiagnosticSchema.parse(await response.json());
}

export async function getDiagnostic(assessmentId: string): Promise<Diagnostic> {
  const payload = await apiRequest<unknown>(
    `/api/v1/prospect-diagnostics/${assessmentId}`,
  );
  return DiagnosticSchema.parse(payload);
}

export async function getDiagnosticRejections(
  assessmentId: string,
): Promise<DiagnosticRejectionList> {
  const payload = await apiRequest<unknown>(
    `/api/v1/prospect-diagnostics/${assessmentId}/rejections`,
  );
  return DiagnosticRejectionListSchema.parse(payload);
}

export async function deleteDiagnostic(assessmentId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/prospect-diagnostics/${assessmentId}`, {
    method: "DELETE",
  });
}

export function diagnosticDownloadUrl(path: string): string {
  return `${apiUrl}${path}`;
}

export const DIAGNOSTIC_STAGES: ReadonlyArray<{
  status: DiagnosticStatus;
  label: string;
}> = [
  { status: "queued", label: "Queue assessment" },
  { status: "ingesting", label: "Import Shopify catalog" },
  { status: "normalizing", label: "Normalize products and variants" },
  { status: "categorizing", label: "Assign furniture taxonomy" },
  { status: "auditing", label: "Run evidence-backed audit" },
  { status: "matching", label: "Test prepared buyer intents" },
  { status: "preparing_reports", label: "Prepare branded deliverables" },
  { status: "completed", label: "Complete" },
];

export function diagnosticStageState(
  current: DiagnosticStatus,
  stage: DiagnosticStatus,
): "completed" | "active" | "pending" | "failed" {
  if (current === "failed") return "failed";
  const currentIndex = DIAGNOSTIC_STAGES.findIndex((item) => item.status === current);
  const stageIndex = DIAGNOSTIC_STAGES.findIndex((item) => item.status === stage);
  if (current === "completed" || stageIndex < currentIndex) return "completed";
  if (stageIndex === currentIndex) return "active";
  return "pending";
}
