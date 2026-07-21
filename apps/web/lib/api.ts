import { HealthResponseSchema, type HealthResponse } from "@catora/contracts";

const apiUrl = process.env.NEXT_PUBLIC_CATORA_API_URL ?? "http://localhost:8000";

export async function fetchApiHealth(fetcher: typeof fetch = fetch): Promise<HealthResponse> {
  const response = await fetcher(`${apiUrl}/health/live`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Catora API health request failed with status ${response.status}`);
  }
  return HealthResponseSchema.parse(await response.json());
}
