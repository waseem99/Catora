import { z } from "zod";
import { apiRequest } from "./auth";

export const ShopifyConfigurationSchema = z.object({
  enabled: z.boolean(),
  required_scopes: z.array(z.string()),
  callback_url: z.string().nullable(),
});

export const ShopifyWebhookDeliverySchema = z.object({
  id: z.string().uuid(),
  topic: z.enum([
    "app/uninstalled",
    "products/create",
    "products/update",
    "products/delete",
  ]),
  status: z.enum(["queued", "completed", "ignored", "failed"]),
  signature_verified: z.literal(true),
  received_at: z.string(),
  processed_at: z.string().nullable(),
  product_id: z.string().nullable(),
  ingestion_job_id: z.string().uuid().nullable(),
});

export const ShopifyInstallationSchema = z.object({
  id: z.string().uuid(),
  workspace_id: z.string().uuid(),
  catalog_source_id: z.string().uuid().nullable(),
  shop_domain: z.string(),
  status: z.enum([
    "pending",
    "active",
    "refresh_required",
    "disconnected",
    "revoked",
    "failed",
  ]),
  granted_scopes: z.array(z.string()),
  token_mode: z.enum(["expiring_offline", "non_expiring_offline"]),
  access_token_expires_at: z.string().nullable(),
  refresh_token_expires_at: z.string().nullable(),
  installed_at: z.string().nullable(),
  refreshed_at: z.string().nullable(),
  disconnected_at: z.string().nullable(),
  last_health_checked_at: z.string().nullable(),
  health: z.enum(["healthy", "refresh_required", "disconnected", "unknown"]),
  detail: z.string(),
  sync_status: z.enum([
    "not_started",
    "queued",
    "coalesced",
    "running",
    "completed",
    "failed",
    "revoked",
  ]),
  last_successful_sync_at: z.string().nullable(),
  last_sync_job_id: z.string().uuid().nullable(),
  last_audit_run_id: z.string().uuid().nullable(),
  product_count: z.number().int().nonnegative(),
  variant_count: z.number().int().nonnegative(),
  warning_count: z.number().int().nonnegative(),
  last_sync_error_type: z.string().nullable(),
  latest_webhook: ShopifyWebhookDeliverySchema.nullable().optional(),
});

const ShopifyInstallStartSchema = z.object({
  authorization_url: z.string().url(),
  expires_at: z.string(),
});

export type ShopifyConfiguration = z.infer<typeof ShopifyConfigurationSchema>;
export type ShopifyInstallation = z.infer<typeof ShopifyInstallationSchema>;
export type ShopifyWebhookDelivery = z.infer<typeof ShopifyWebhookDeliverySchema>;

export async function getShopifyConfiguration(
  workspaceId: string,
): Promise<ShopifyConfiguration> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/shopify/configuration`,
  );
  return ShopifyConfigurationSchema.parse(payload);
}

export async function getShopifyInstallation(
  workspaceId: string,
): Promise<ShopifyInstallation | null> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/shopify/installation`,
  );
  return payload === null ? null : ShopifyInstallationSchema.parse(payload);
}

export async function getLatestShopifyWebhook(
  workspaceId: string,
): Promise<ShopifyWebhookDelivery | null> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/shopify/webhooks/latest`,
  );
  return payload === null ? null : ShopifyWebhookDeliverySchema.parse(payload);
}

export async function startShopifyInstallation(
  workspaceId: string,
  shopDomain: string,
): Promise<string> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/shopify/installations/start`,
    {
      method: "POST",
      body: JSON.stringify({ shop_domain: shopDomain }),
    },
  );
  return ShopifyInstallStartSchema.parse(payload).authorization_url;
}

export async function syncShopifyInstallation(
  workspaceId: string,
): Promise<ShopifyInstallation> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/shopify/installation/sync`,
    { method: "POST" },
  );
  return ShopifyInstallationSchema.parse(payload);
}

export async function refreshShopifyInstallation(
  workspaceId: string,
): Promise<ShopifyInstallation> {
  const payload = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/shopify/installation/refresh`,
    { method: "POST" },
  );
  return ShopifyInstallationSchema.parse(payload);
}

export async function disconnectShopifyInstallation(
  workspaceId: string,
): Promise<void> {
  await apiRequest<void>(
    `/api/v1/workspaces/${workspaceId}/shopify/installation`,
    { method: "DELETE" },
  );
}
