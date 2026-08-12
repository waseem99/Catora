import { HealthResponseSchema, type HealthResponse } from "@catora/contracts";

function runtimeApiUrl(): string {
  return (
    process.env.CATORA_API_URL?.trim() ||
    process.env.NEXT_PUBLIC_CATORA_API_URL?.trim() ||
    "http://localhost:8000"
  ).replace(/\/+$/, "");
}

export async function fetchApiHealth(fetcher: typeof fetch = fetch): Promise<HealthResponse> {
  const response = await fetcher(`${runtimeApiUrl()}/health/live`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Catora API health request failed with status ${response.status}`);
  }
  return HealthResponseSchema.parse(await response.json());
}
