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

export function formatCatalogValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
}
