import { z } from "zod";
import { apiRequest } from "./auth";

const uuid = z.string().uuid();

export const MeasurementAccountSchema = z.object({
  id: uuid,
  provider: z.string(),
  external_account_id: z.string(),
  capabilities: z.record(z.string(), z.unknown()),
  status: z.string(),
  sync_checkpoint: z.record(z.string(), z.unknown()),
  disconnected_at: z.string().nullable(),
});

export const GoogleMeasurementSyncSchema = z.object({
  account_id: uuid,
  provider: z.enum(["google_search_console", "ga4"]),
  properties: z.number().int().nonnegative(),
  accepted: z.number().int().nonnegative(),
  duplicate: z.number().int().nonnegative(),
});

export type MeasurementAccount = z.infer<typeof MeasurementAccountSchema>;
export type GoogleMeasurementSync = z.infer<typeof GoogleMeasurementSyncSchema>;

export async function listMeasurementAccounts(
  workspaceId: string,
): Promise<MeasurementAccount[]> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/measurements/accounts`,
  );
  return z.array(MeasurementAccountSchema).parse(value);
}

export async function connectGoogleMeasurement(
  workspaceId: string,
  input: {
    provider: "google_search_console" | "ga4";
    credential_reference: string;
    property_allowlist: string[];
  },
): Promise<GoogleMeasurementSync> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/measurements/connect-google`,
    { method: "POST", body: JSON.stringify(input) },
  );
  return GoogleMeasurementSyncSchema.parse(value);
}

export async function syncGoogleMeasurement(
  workspaceId: string,
  accountId: string,
): Promise<GoogleMeasurementSync> {
  const value = await apiRequest<unknown>(
    `/api/v1/workspaces/${workspaceId}/measurements/accounts/${accountId}/sync`,
    { method: "POST" },
  );
  return GoogleMeasurementSyncSchema.parse(value);
}
