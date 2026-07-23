import { z } from "zod";
import { apiRequest, csrfToken } from "./auth";

const apiUrl = process.env.NEXT_PUBLIC_CATORA_API_URL ?? "http://localhost:8000";
const uuid = z.string().uuid();

export const CsvUploadSchema = z.object({
  object_key: z.string(),
  size_bytes: z.number().int().positive(),
  content_type: z.string(),
});

export const CatalogSourceSchema = z.object({
  id: uuid,
  workspace_id: uuid,
  name: z.string(),
  source_type: z.string(),
  status: z.string(),
  storefront_id: uuid.nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const SourceValidationSchema = z.object({
  valid: z.boolean(),
  errors: z.array(z.string()),
  warnings: z.array(z.string()),
  discovered_fields: z.array(z.string()),
});

export const IngestionJobSchema = z.object({
  id: uuid,
  workspace_id: uuid,
  catalog_source_id: uuid,
  status: z.enum([
    "queued",
    "validating",
    "running",
    "partially_completed",
    "completed",
    "failed",
    "cancelled",
  ]),
  processed_count: z.number().int().nonnegative(),
  success_count: z.number().int().nonnegative(),
  rejection_count: z.number().int().nonnegative(),
  warning_count: z.number().int().nonnegative(),
  checkpoint: z.record(z.string(), z.unknown()),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type IngestionJob = z.infer<typeof IngestionJobSchema>;
export type SourceValidation = z.infer<typeof SourceValidationSchema>;

export async function uploadShopifyCsv(workspaceId: string, file: File) {
  const headers = new Headers({
    Accept: "application/json",
    "Content-Type": "text/csv",
  });
  const csrf = csrfToken();
  if (csrf) headers.set("X-CSRF-Token", csrf);

  const response = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/catalog-uploads/csv`, {
    method: "PUT",
    headers,
    body: file,
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Upload failed with status ${response.status}`);
  }
  return CsvUploadSchema.parse(await response.json());
}

export async function createShopifyCsvSource(
  workspaceId: string,
  objectKey: string,
  sourceName: string,
) {
  const payload = await apiRequest<unknown>(`/api/v1/workspaces/${workspaceId}/catalog-sources`, {
    method: "POST",
    body: JSON.stringify({
      name: sourceName,
      source_type: "csv",
      profile: "shopify",
      object_key: objectKey,
      mapping: {
        product_id: "Handle",
        title: "Title",
        variant_id: "Variant SKU",
        sku: "Variant SKU",
        description: "Body (HTML)",
        price: "Variant Price",
        availability: "Variant Inventory Qty",
        category: "Type",
        image_url: "Image Src",
      },
    }),
  });
  return CatalogSourceSchema.parse(payload);
}

export async function validateCatalogSource(workspaceId: string, sourceId: string) {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/catalog-sources/${sourceId}/validate`,
    { method: "POST" },
  );
  return SourceValidationSchema.parse(payload);
}

export async function startCatalogIngestion(workspaceId: string, sourceId: string) {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/catalog-sources/${sourceId}/jobs`,
    { method: "POST" },
  );
  return IngestionJobSchema.parse(payload);
}

export async function listIngestionJobs(workspaceId: string): Promise<IngestionJob[]> {
  const payload = await apiRequest<unknown[]>(`/api/v1/workspaces/${workspaceId}/ingestion-jobs`);
  return z.array(IngestionJobSchema).parse(payload);
}

export function normalizationSummary(job: IngestionJob): Record<string, unknown> | null {
  const value = job.checkpoint.normalization;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
