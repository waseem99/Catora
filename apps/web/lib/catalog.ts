export type ProductListOptions = {
  query?: string;
  hasWarnings?: boolean;
  limit?: number;
  offset?: number;
};

export function catalogProductsPath(
  workspaceId: string,
  options: ProductListOptions = {},
): string {
  const params = new URLSearchParams();
  params.set("status", "active");
  params.set("limit", String(options.limit ?? 25));
  params.set("offset", String(options.offset ?? 0));
  const query = options.query?.trim();
  if (query) params.set("query", query);
  if (options.hasWarnings !== undefined) {
    params.set("has_warnings", String(options.hasWarnings));
  }
  return `/api/v1/workspaces/${workspaceId}/products?${params.toString()}`;
}

export function catalogProductPath(workspaceId: string, productId: string): string {
  return `/api/v1/workspaces/${workspaceId}/products/${productId}`;
}

export function catalogProvenancePath(
  workspaceId: string,
  productId: string,
): string {
  return `/api/v1/workspaces/${workspaceId}/products/${productId}/provenance`;
}

export function identityCandidatesPath(workspaceId: string): string {
  return `/api/v1/workspaces/${workspaceId}/identity-candidates?status=pending&limit=100`;
}

export function refreshIdentityCandidatesPath(workspaceId: string): string {
  return `/api/v1/workspaces/${workspaceId}/identity-candidates/refresh`;
}

export function linkProductIdentityPath(workspaceId: string, productId: string): string {
  return `/api/v1/workspaces/${workspaceId}/products/${productId}/identity-link`;
}

export function unlinkProductIdentityPath(workspaceId: string, productId: string): string {
  return `/api/v1/workspaces/${workspaceId}/products/${productId}/identity-unlink`;
}

export function rejectIdentityCandidatePath(
  workspaceId: string,
  candidateId: string,
): string {
  return `/api/v1/workspaces/${workspaceId}/identity-candidates/${candidateId}/reject`;
}

export function productIdentityPath(workspaceId: string, productId: string): string {
  return `/api/v1/workspaces/${workspaceId}/products/${productId}/identity`;
}

export function formatCatalogValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
}
